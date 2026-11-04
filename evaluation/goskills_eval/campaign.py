"""Plan/run a sequential benchmark matrix without score retries or overwritten trials."""
from pathlib import Path
import argparse, json, subprocess, sys, re, hashlib, os
from .common import write, now
METHODS = ('noskills', 'vanilla', 'vector', 'native-gos', 'goskills-d')
TRACKS = {'skillsbench': 'skillsbench', 'alfworld': 'alfworld', 'tb2': 'terminalbench2'}
ROOT = Path(__file__).resolve().parents[2]

def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value) or value in {'.','..'}:
        raise ValueError('Invalid task ID')
    return value

def resource(config, key, base):
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError('Missing configuration path: '+key)
    path = Path(value).expanduser()
    path = (base/path).resolve() if not path.is_absolute() else path.resolve()
    if not path.exists():
        raise FileNotFoundError('Missing configuration resource '+key+': '+str(path))
    return str(path)

def build_plan(config_path, benchmark, methods, output, tasks=None):
    config_path=Path(config_path).resolve();base=config_path.parent
    cfg=json.loads(config_path.read_text());output=Path(output).resolve()
    if output.exists():raise FileExistsError('Use a new campaign output directory')
    if not methods or len(set(methods))!=len(methods) or any(m not in METHODS for m in methods):raise ValueError('Invalid methods')
    tracks=list(TRACKS) if benchmark=='all' else [benchmark]
    if any(t not in TRACKS for t in tracks):raise ValueError('Invalid benchmark')
    if tasks and len(tracks)!=1:raise ValueError('--tasks requires one benchmark')
    from .method_backend import validate_output
    inputs={'config':config_path}
    for key in ['skills_root','pool','upstream','workspace']:
        if cfg.get(key):inputs[key]=base/Path(cfg[key]).expanduser()
    for track in tracks:
        for key in ['tasks_root','games_manifest','data_root','config']:
            if cfg.get(track,{}).get(key):inputs[track+'_'+key]=base/Path(cfg[track][key]).expanduser()
    validate_output(output,**inputs)
    # Preserve the venv executable path: resolving its symlink loses that venv.
    value=cfg.get('retrieval_python')
    retrieval_python=str((base/Path(value).expanduser()).absolute()) if value else sys.executable
    if not Path(retrieval_python).is_file() or not os.access(retrieval_python,os.X_OK):raise ValueError('retrieval_python must be an executable Python path')
    members=json.loads((ROOT/'configs/task_ids.json').read_text())
    jobs=[]
    for track in tracks:
        spec=cfg.get(track)
        if not isinstance(spec,dict):raise ValueError('Missing benchmark configuration: '+track)
        selected=tasks or spec.get('tasks') or members[track]
        if not isinstance(selected,list) or not selected or len(set(selected))!=len(selected):raise ValueError('Empty or duplicate tasks')
        games={}
        if track=='alfworld':
            manifest=Path(resource(spec,'games_manifest',base))
            games=json.loads(manifest.read_text())
            if not isinstance(games,dict):raise ValueError('ALF game manifest must map IDs to relative game paths')
        for method in methods:
            extra=[]
            if method!='noskills':extra+=['--skills-root',resource(cfg,'skills_root',base)]
            if method=='goskills-d':extra+=['--pool',resource(cfg,'pool',base)]
            if method in {'vanilla','vector','native-gos'} or track=='alfworld' or (track=='skillsbench' and method!='noskills'):extra+=['--upstream',resource(cfg,'upstream',base)]
            if method in {'vector','native-gos'}:extra+=['--workspace',resource(cfg,'workspace',base)]
            for task in selected:
                safe_id(task);dest=output/track/method/task
                command=[retrieval_python if track=='alfworld' else sys.executable,str(ROOT/'evaluation'/TRACKS[track]/'run.py'),'--method',method,'--output',str(dest),*extra]
                if track=='alfworld':
                    if task not in games:raise ValueError('Missing ALF game ID: '+task)
                    item=games[task];item={'path':item} if isinstance(item,str) else item
                    game=(Path(resource(spec,'data_root',base))/item['path']).resolve()
                    if not game.is_relative_to(Path(resource(spec,'data_root',base))):raise ValueError('ALF path escapes data root')
                    if not game.is_file():raise FileNotFoundError(game)
                    if item.get('sha256') and hashlib.sha256(game.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('ALF game hash mismatch: '+task)
                    command+=['--game-file',str(game),'--config',resource(spec,'config',base),'--data-root',resource(spec,'data_root',base)]
                else:
                    task_path=Path(resource(spec,'tasks_root',base))/task
                    if not (task_path/'task.toml').is_file():raise FileNotFoundError(task_path/'task.toml')
                    command+=['--task',str(task_path)]
                    if method!='noskills':command+=['--retrieval-python',retrieval_python]
                jobs.append({'benchmark':track,'method':method,'task':task,'output':str(dest),'output_relative':dest.relative_to(output).as_posix(),'command':command})
    return {'schema_version':1,'status':'PLAN_ONLY','created_at':now(),'config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest(),'output':str(output),'count':len(jobs),'methods':methods,'jobs':jobs,'attempts_per_job':1,'execution':'sequential; stop on a failed trial; no automatic retry'}

def execute_plan(plan, run_command=subprocess.run):
    out=Path(plan['output']);out.mkdir(parents=True,exist_ok=False)
    write(out/'PLAN.json',plan,True);rows=[]
    try:
        for i,job in enumerate(plan['jobs']):
            log=out/'logs'/f'{i:05d}.log';log.parent.mkdir(exist_ok=True)
            with log.open('xb') as handle:
                result=run_command([*job['command'],'--execute'],stdout=handle,stderr=subprocess.STDOUT)
            receipt=Path(job['output'])/'receipt.json'
            valid=False;receipt_sha=None
            if result.returncode==0 and receipt.is_file():
                raw=receipt.read_bytes();r=json.loads(raw);receipt_sha=hashlib.sha256(raw).hexdigest()
                valid=r.get('status')=='VALID' and r.get('method')==job['method']
            rows.append({k:job[k] for k in ['benchmark','method','task','output_relative']}|{'return_code':result.returncode,'status':'VALID' if valid else 'PROCESS_FAILED','receipt_sha256':receipt_sha})
            write(out/'STATUS.json',{'status':'RUNNING' if valid else 'BLOCKED','finished':len(rows),'planned':len(plan['jobs']),'rows':rows})
            if not valid:raise RuntimeError('Trial did not produce a VALID receipt; remaining jobs were not dispatched')
    except BaseException:
        write(out/'STATUS.json',{'status':'BLOCKED','finished':len(rows),'planned':len(plan['jobs']),'rows':rows});raise
    write(out/'STATUS.json',{'status':'COMPLETE','finished':len(rows),'planned':len(plan['jobs']),'rows':rows})

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--benchmark',choices=[*TRACKS,'all'],default='all');p.add_argument('--methods',default='all',help='all or comma-separated method IDs');p.add_argument('--tasks',help='comma-separated IDs for one benchmark');p.add_argument('--output',type=Path,required=True);p.add_argument('--execute',action='store_true',help='Actually run paid new trials; omitted by default')
    a=p.parse_args();methods=list(METHODS) if a.methods=='all' else a.methods.split(',');plan=build_plan(a.config,a.benchmark,methods,a.output,a.tasks.split(',') if a.tasks else None)
    if a.execute:execute_plan(plan)
    else:print(json.dumps(plan,indent=2))
if __name__=='__main__':main()
