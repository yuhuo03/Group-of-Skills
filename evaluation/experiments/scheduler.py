"""Single-attempt concurrent campaigns with durable claims and safe resume."""
import concurrent.futures as futures
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading

from goskills_eval.utils import now
from goskills_eval.experiments.bindings import receipt_evidence, verify_bindings


def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def sha(value):return hashlib.sha256(encoded(value)).hexdigest()


def durable(path,value,exclusive=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise ValueError('Refusing symlink state')
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as handle:
            handle.write(encoded(value));handle.flush();os.fsync(handle.fileno())
        if exclusive:os.link(tmp,path)
        else:os.replace(tmp,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


@contextmanager
def campaign_lock(root):
    root=Path(root)
    if root.resolve()!=root.absolute():raise ValueError('Campaign path contains a symlink')
    fd=os.open(root/'controller.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Campaign controller or owned runner is still active') from None
        yield fd
    finally:
        # Never LOCK_UN: children inherit the same open file description. Closing
        # only our reference retains the lock until every owned runner exits.
        os.close(fd)


@contextmanager
def stop_signals(event):
    previous={}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT,signal.SIGTERM):
            previous[sig]=signal.getsignal(sig);signal.signal(sig,lambda *_:event.set())
    try:yield
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)


def validate_plan(plan):
    if plan.get('schema_version')!=2 or plan.get('attempts_per_job')!=1:raise ValueError('Unsupported campaign plan')
    limits=plan.get('scheduling',{})
    if set(limits)!={'workers','per_method'}:raise ValueError('Missing concurrency limits')
    if any(type(v) is not int or not 1<=v<=20 for v in limits.values()):raise ValueError('Concurrency limits must be 1..20')
    if limits['per_method']>limits['workers']:raise ValueError('Per-method limit exceeds worker limit')
    root=Path(plan['output'])
    if not root.is_absolute() or root.resolve()!=root:raise ValueError('Campaign output must be canonical absolute path')
    if not plan.get('jobs') or plan['count']!=len(plan['jobs']):raise ValueError('Invalid planned job count')
    seen=set()
    for job in plan['jobs']:
        key=tuple(job[k] for k in ('benchmark','method','task'))
        if key in seen:raise ValueError('Duplicate planned job')
        seen.add(key)
        relative=Path(job['output_relative'])
        if relative.is_absolute() or '..' in relative.parts or relative==Path('.'):raise ValueError('Unsafe job output')
        dest=root/relative
        if str(dest)!=job['output'] or dest.resolve()!=dest:raise ValueError('Job output path mismatch or symlink')
        command=job['command']
        if not isinstance(command,list) or not all(isinstance(x,str) for x in command) or '--execute' in command:raise ValueError('Invalid planned command')
        if command.count('--output')!=1 or command[command.index('--output')+1]!=str(dest):raise ValueError('Command output mismatch')
        if command.count('--method')!=1 or command[command.index('--method')+1]!=job['method']:raise ValueError('Command method mismatch')


def load_plan(root):
    root=Path(root).absolute()
    for name in ('PLAN.json','PLAN_BINDING.json'):
        if (root/name).is_symlink():raise ValueError('Symlink plan')
    plan=json.loads((root/'PLAN.json').read_text());binding=json.loads((root/'PLAN_BINDING.json').read_text())
    if binding!={'plan_sha256':sha(plan)}:raise ValueError('Campaign plan changed')
    if plan['output']!=str(root):raise ValueError('Resume at the original campaign path; relocated archives remain readable')
    validate_plan(plan)
    return plan


def row(job,outcome):
    return {k:job[k] for k in ('benchmark','method','task','output_relative')}|{
        k:outcome.get(k) for k in ('return_code','status','receipt_sha256','resources_clear')}


def outcome_for(plan,index,return_code,*,recovered=False,error_type=None):
    job=plan['jobs'][index]
    result={'index':index,'plan_sha256':sha(plan),'job_sha256':sha(job),'return_code':return_code,
            'finished_at':now(),'status':'PROCESS_FAILED','receipt_sha256':None,'artifacts':{},'resources_clear':False}
    if recovered:result['recovered_after_controller_exit']=True
    if error_type:result['error_type']=error_type
    try:
        evidence=receipt_evidence(plan,job);result.update(evidence)
        if evidence['valid'] and (return_code==0 or recovered):result['status']='VALID'
    except (OSError,ValueError,KeyError,TypeError) as exc:
        result['evidence_error_type']=type(exc).__name__
    return result


def reconcile(plan):
    root=Path(plan['output']);outcomes={};pending=[]
    for directory in ('claims','outcomes','logs'):
        if (root/directory).is_symlink():raise ValueError('Symlink campaign evidence directory')
    expected={f'{i:05d}.json' for i in range(plan['count'])}
    for directory in ('claims','outcomes'):
        path=root/directory
        if path.exists() and any(p.name not in expected for p in path.iterdir() if not p.name.startswith('.')):raise ValueError('Unplanned campaign evidence')
    for i,job in enumerate(plan['jobs']):
        claim_path=root/'claims'/f'{i:05d}.json';outcome_path=root/'outcomes'/f'{i:05d}.json'
        if claim_path.is_symlink() or outcome_path.is_symlink():raise ValueError('Symlink attempt evidence')
        binding={'index':i,'plan_sha256':sha(plan),'job_sha256':sha(job)}
        if not claim_path.exists():
            if outcome_path.exists() or Path(job['output']).exists() or (root/'logs'/f'{i:05d}.log').exists():raise ValueError('Unclaimed output exists; refusing dispatch')
            pending.append(i);continue
        claim=json.loads(claim_path.read_text())
        if any(claim.get(k)!=v for k,v in binding.items()):raise ValueError('Claim identity mismatch')
        if not outcome_path.exists():
            # Only reached with exclusive lock: inherited descriptors prove every
            # runner from the previous controller exited. Never replay this claim.
            recovered=outcome_for(plan,i,None,recovered=True)
            if not recovered['resources_clear'] or recovered.get('evidence_error_type'):raise RuntimeError('Claim has no confirmed terminal clear receipt; inspect it without retrying')
            durable(outcome_path,recovered,exclusive=True)
        result=json.loads(outcome_path.read_text())
        if any(result.get(k)!=v for k,v in binding.items()):raise ValueError('Outcome identity mismatch')
        evidence=outcome_for(plan,i,result['return_code'],recovered=result.get('recovered_after_controller_exit',False))
        for key in ('status','receipt_sha256','artifacts','resources_clear'):
            if evidence[key]!=result.get(key):raise ValueError('Completed result evidence changed')
        outcomes[i]=result
    return outcomes,pending


def run_job(plan,index,lock_fd,run_command):
    root=Path(plan['output']);log=root/'logs'/f'{index:05d}.log';log.parent.mkdir(exist_ok=True)
    code=None;error=None
    try:
        with log.open('xb') as handle:
            process=run_command([*plan['jobs'][index]['command'],'--execute'],stdout=handle,stderr=subprocess.STDOUT,
                                pass_fds=(lock_fd,),start_new_session=True)
            code=process.returncode
    except Exception as exc:error=type(exc).__name__
    result=outcome_for(plan,index,code,error_type=error)
    durable(root/'outcomes'/f'{index:05d}.json',result,exclusive=True)
    return result


def save_status(plan,outcomes,active,status):
    durable(Path(plan['output'])/'STATUS.json',{'status':status,'finished':len(outcomes),'planned':plan['count'],
        'running':sorted(active),'queued':plan['count']-len(outcomes)-len(active),
        'rows':[row(plan['jobs'][i],outcomes[i]) for i in sorted(outcomes)]})


def schedule(plan,fd,run_command,stop_event):
    outcomes,pending=reconcile(plan)
    if pending and any(not result['resources_clear'] for result in outcomes.values()):
        raise RuntimeError('Previous attempt resources are not confirmed clear; resume refused')
    active={};failed=False;limits=plan['scheduling']
    with stop_signals(stop_event), futures.ThreadPoolExecutor(max_workers=limits['workers']) as executor:
        try:
            while pending or active:
                for future,index in list(active.items()):
                    if future.done():
                        outcomes[index]=future.result();del active[future]
                        if outcomes[index]['status']!='VALID':failed=True
                        save_status(plan,outcomes,active.values(),'DRAINING' if failed or stop_event.is_set() else 'RUNNING')
                if not failed and not stop_event.is_set() and len(active)<limits['workers']:
                    counts={}
                    for index in active.values():
                        method=plan['jobs'][index]['method'];counts[method]=counts.get(method,0)+1
                    index=next((i for i in pending if counts.get(plan['jobs'][i]['method'],0)<limits['per_method']),None)
                    if index is not None:
                        job=plan['jobs'][index]
                        if Path(job['output']).exists():raise ValueError('Output appeared before dispatch')
                        durable(Path(plan['output'])/'claims'/f'{index:05d}.json',
                            {'index':index,'plan_sha256':sha(plan),'job_sha256':sha(job),'claimed_at':now()},exclusive=True)
                        pending.remove(index);future=executor.submit(run_job,plan,index,fd,run_command);active[future]=index
                        save_status(plan,outcomes,active.values(),'RUNNING');continue
                if not active:break
                futures.wait(active,timeout=0.2,return_when=futures.FIRST_COMPLETED)
        except BaseException:
            stop_event.set()
            # Drain every already-dispatched runner before releasing our lock.
            for future,index in active.items():
                try:outcomes[index]=future.result()
                except BaseException:pass
            save_status(plan,outcomes,[],'BLOCKED');raise
    status='COMPLETE' if len(outcomes)==plan['count'] and all(r['status']=='VALID' for r in outcomes.values()) else 'BLOCKED'
    save_status(plan,outcomes,[],status)
    if status!='COMPLETE':raise RuntimeError('Campaign stopped with unresolved or queued trials; VALID receipt results are preserved')


def execute_plan(plan,run_command=subprocess.run,*,stop_event=None):
    validate_plan(plan);verify_bindings(plan)
    root=Path(plan['output']);root.mkdir(parents=True,exist_ok=False)
    with campaign_lock(root) as fd:
        durable(root/'PLAN.json',plan,exclusive=True)
        durable(root/'PLAN_BINDING.json',{'plan_sha256':sha(plan)},exclusive=True)
        schedule(plan,fd,run_command,stop_event or threading.Event())


def resume_campaign(root,*,execute=False,run_command=subprocess.run,stop_event=None):
    with campaign_lock(root) as fd:
        plan=load_plan(root);verify_bindings(plan)
        if not execute:
            # A preview must not recover/write outcomes or alter any trial.
            claims=list((Path(root)/'claims').glob('*.json'))
            return {'status':'RESUME_PLAN_ONLY','planned':plan['count'],'claimed':len(claims),
                    'never_claimed':plan['count']-len(claims),'scheduling':plan['scheduling'],
                    'note':'Execution revalidates claims, outcomes and resource clearance before dispatch.'}
        schedule(plan,fd,run_command,stop_event or threading.Event())
