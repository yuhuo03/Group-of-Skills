import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace as NS
import pytest
from campaign_fixture import complete
import test_campaign as campaign_tests
from goskills_eval.experiments.run import build_plan
from goskills_eval.experiments.scheduler import (execute_plan,resume_campaign,campaign_lock,
    durable,sha,reconcile,load_plan)


def plan(root,**kwargs):
    cfg=campaign_tests.CampaignTests().fixture(root)
    return build_plan(cfg,'tb2',['noskills','vanilla','vector','native-gos','goskills-d'],root/'run',**kwargs)


def fake(plan,calls,**overrides):
    def run(command,**kwargs):
        job=next(j for j in plan['jobs'] if j['output']==command[command.index('--output')+1])
        calls.append(job['method']);complete(job,plan['runtime'],**overrides)
        return NS(returncode=1 if overrides.get('failed') else 0)
    return run


def test_interrupt_resume_preserves_valid_zero_and_never_dispatches_claim_again(tmp_path):
    p=plan(tmp_path);calls=[];stop=threading.Event()
    wrapped=fake(p,calls)
    def first(*a,**k):result=wrapped(*a,**k);stop.set();return result
    with pytest.raises(RuntimeError):execute_plan(p,first,stop_event=stop)
    root=Path(p['output']);original=(root/'tb2/noskills/sample/receipt.json').read_bytes()
    assert calls==['noskills']
    preview=resume_campaign(root)
    assert preview['claimed']==1 and preview['never_claimed']==4
    resume_campaign(root,execute=True,run_command=fake(p,calls))
    assert len(calls)==5 and len(set(calls))==5
    assert original==(root/'tb2/noskills/sample/receipt.json').read_bytes()
    assert json.loads((root/'STATUS.json').read_text())['status']=='COMPLETE'
    resume_campaign(root,execute=True,run_command=lambda *a,**k:pytest.fail('duplicate'))


def test_failed_clear_attempt_stays_failed_but_remaining_can_continue(tmp_path):
    p=plan(tmp_path);calls=[]
    with pytest.raises(RuntimeError):execute_plan(p,fake(p,calls,failed=True))
    failed=Path(p['jobs'][0]['output'])/'receipt.json';original=failed.read_bytes()
    with pytest.raises(RuntimeError):resume_campaign(p['output'],execute=True,run_command=fake(p,calls))
    assert len(calls)==5 and original==failed.read_bytes()
    rows=json.loads((Path(p['output'])/'STATUS.json').read_text())['rows']
    assert [r['status'] for r in rows]==['PROCESS_FAILED']+['VALID']*4


def test_uncleared_failure_refuses_resume_without_calls(tmp_path):
    p=plan(tmp_path);calls=[]
    with pytest.raises(RuntimeError):execute_plan(p,fake(p,calls,failed=True,clear=False))
    with pytest.raises(RuntimeError,match='resources'):resume_campaign(p['output'],execute=True,run_command=fake(p,calls))
    assert len(calls)==1


@pytest.mark.parametrize('changed',['input','workspace_binding','source','plan','receipt','artifact','unclaimed_output'])
def test_changed_bindings_and_results_refuse_dispatch(tmp_path,changed):
    p=plan(tmp_path);stop=threading.Event();calls=[];run=fake(p,calls)
    def first(*a,**k):r=run(*a,**k);stop.set();return r
    with pytest.raises(RuntimeError):execute_plan(p,first,stop_event=stop)
    root=Path(p['output'])
    if changed=='input':(tmp_path/'tasks/sample/instruction.md').write_text('changed')
    elif changed=='workspace_binding':
        from goskills_eval.workspace import identity_path
        identity_path(tmp_path/'workspace').write_text('{}')
    elif changed=='source':
        # Alter only saved binding bytes, never shared evaluator files.
        data=json.loads((root/'PLAN.json').read_text());data['sources'][next(iter(data['sources']))]['sha256']='0'*64
        durable(root/'PLAN.json',data);durable(root/'PLAN_BINDING.json',{'plan_sha256':sha(data)})
    elif changed=='plan':
        data=json.loads((root/'PLAN.json').read_text());data['runtime']['model']='changed';durable(root/'PLAN.json',data)
    elif changed=='receipt':
        path=Path(p['jobs'][0]['output'])/'receipt.json';data=json.loads(path.read_text());data['reward']=1;path.write_text(json.dumps(data))
    elif changed=='artifact':(Path(p['jobs'][0]['output'])/'trials/synthetic/result.json').write_text('changed')
    else:Path(p['jobs'][1]['output']).mkdir(parents=True)
    with pytest.raises((ValueError,RuntimeError)):resume_campaign(root,execute=True,run_command=fake(p,calls))
    assert len(calls)==1


def test_lost_outcome_recovers_terminal_clear_receipt_and_never_replays(tmp_path):
    p=plan(tmp_path);calls=[];stop=threading.Event();run=fake(p,calls)
    def first(*a,**k):result=run(*a,**k);stop.set();return result
    with pytest.raises(RuntimeError):execute_plan(p,first,stop_event=stop)
    root=Path(p['output']);(root/'outcomes/00000.json').unlink() # crash-window simulation
    resume_campaign(root,execute=True,run_command=fake(p,calls))
    recovered=json.loads((root/'outcomes/00000.json').read_text())
    assert recovered['recovered_after_controller_exit'] and recovered['return_code'] is None
    assert calls.count('noskills')==1


def test_claim_without_terminal_receipt_is_never_replayed(tmp_path):
    p=plan(tmp_path);root=Path(p['output']);root.mkdir()
    durable(root/'PLAN.json',p,True);durable(root/'PLAN_BINDING.json',{'plan_sha256':sha(p)},True)
    durable(root/'claims/00000.json',{'index':0,'plan_sha256':sha(p),'job_sha256':sha(p['jobs'][0])},True)
    with pytest.raises(RuntimeError,match='terminal clear receipt'):
        resume_campaign(root,execute=True,run_command=lambda *a,**k:pytest.fail('replayed'))


def test_inherited_lock_survives_controller_close_until_owned_child_exits(tmp_path):
    ready=tmp_path/'ready';release=tmp_path/'release'
    code='import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch();\nwhile not pathlib.Path(sys.argv[2]).exists(): time.sleep(.01)'
    with campaign_lock(tmp_path) as fd:
        child=subprocess.Popen([sys.executable,'-c',code,str(ready),str(release)],pass_fds=(fd,),start_new_session=True)
    try:
        deadline=time.monotonic()+5
        while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
        assert ready.exists()
        with pytest.raises(RuntimeError,match='still active'):
            with campaign_lock(tmp_path):pass
        release.touch();child.wait(timeout=5)
        with campaign_lock(tmp_path):pass
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=5)


def test_concurrency_caps_and_failure_drains_without_further_dispatch(tmp_path):
    p=plan(tmp_path,workers=3,per_method=1);calls=[];started=threading.Event();release=threading.Event();lock=threading.Lock();active=0;peak=0
    def run(command,**kwargs):
        nonlocal active,peak
        job=next(j for j in p['jobs'] if j['output']==command[command.index('--output')+1])
        with lock:
            calls.append(job['method']);active+=1;peak=max(peak,active)
            if active==3:started.set()
        assert started.wait(5)
        if job['method']=='noskills':complete(job,p['runtime'],failed=True);code=1
        else:
            assert release.wait(5);complete(job,p['runtime']);code=0
        with lock:active-=1
        return NS(returncode=code)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future=executor.submit(execute_plan,p,run)
        assert started.wait(5)
        deadline=time.monotonic()+5;state={}
        while time.monotonic()<deadline:
            path=Path(p['output'])/'STATUS.json'
            if path.exists():state=json.loads(path.read_text())
            if state.get('status')=='DRAINING':break
            time.sleep(.01)
        assert state.get('status')=='DRAINING' and len(calls)==3 and not future.done()
        release.set()
        with pytest.raises(RuntimeError):future.result(timeout=5)
    assert peak==3 and len(calls)==3 and active==0
    rows=json.loads((Path(p['output'])/'STATUS.json').read_text())['rows']
    assert len(rows)==3 and sum(r['status']=='VALID' for r in rows)==2


def test_per_method_limit_with_multiple_tasks(tmp_path):
    import shutil
    cfg=campaign_tests.CampaignTests().fixture(tmp_path)
    shutil.copytree(tmp_path/'tasks/sample',tmp_path/'tasks/second')
    data=json.loads(cfg.read_text());data['tb2']['tasks']=['sample','second'];cfg.write_text(json.dumps(data))
    p=build_plan(cfg,'tb2',['noskills','vanilla'],tmp_path/'run',workers=4,per_method=1)
    lock=threading.Lock();active={};peaks={};total_peak=0;wave=threading.Barrier(2)
    def run(command,**kwargs):
        nonlocal total_peak
        job=next(j for j in p['jobs'] if j['output']==command[command.index('--output')+1]);method=job['method']
        with lock:
            active[method]=active.get(method,0)+1;peaks[method]=max(peaks.get(method,0),active[method]);total_peak=max(total_peak,sum(active.values()))
        wave.wait(timeout=5);complete(job,p['runtime'])
        with lock:active[method]-=1
        return NS(returncode=0)
    execute_plan(p,run)
    assert peaks=={'noskills':1,'vanilla':1} and total_peak==2


def test_real_controller_crash_keeps_owned_runner_lock_and_recovers_without_replay(tmp_path):
    from goskills_eval.experiments.bindings import fingerprint
    p=plan(tmp_path);root=Path(p['output']);helper=Path(__file__).parent/'campaign_fixture.py'
    runner=tmp_path/'synthetic_runner.py'
    runner.write_text('''import argparse,json,pathlib,sys,time
p=argparse.ArgumentParser();p.add_argument('--method');p.add_argument('--output');p.add_argument('--execute',action='store_true');a=p.parse_args()
out=pathlib.Path(a.output);root=out.parents[2];plan=json.loads((root/'PLAN.json').read_text());job=next(j for j in plan['jobs'] if j['output']==str(out))
with (root/'physical_calls.txt').open('a') as f:f.write(a.method+'\\n')
if a.method=='noskills':
 (root/'ready').touch();deadline=time.monotonic()+15
 while not (root/'release').exists():
  if time.monotonic()>deadline:raise RuntimeError('synthetic release timed out')
  time.sleep(.01)
sys.path.insert(0,HELPER)
from campaign_fixture import complete
complete(job,plan['runtime'])
'''.replace('HELPER',repr(str(helper.parent))))
    for job in p['jobs']:
        job['command']=[sys.executable,str(runner),'--method',job['method'],'--output',job['output']]
    p['sources'][str(runner)]=fingerprint(runner);p['sources'][str(helper)]=fingerprint(helper)
    frozen=tmp_path/'synthetic_plan.json';frozen.write_text(json.dumps(p))
    code='import json,sys; from goskills_eval.experiments.scheduler import execute_plan; execute_plan(json.load(open(sys.argv[1])))'
    controller=subprocess.Popen([sys.executable,'-c',code,str(frozen)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    try:
        deadline=time.monotonic()+10
        while not (root/'ready').exists() and time.monotonic()<deadline:
            assert controller.poll() is None
            time.sleep(.01)
        assert (root/'ready').exists()
        controller.kill();controller.wait(timeout=5) # only this test-owned controller
        with pytest.raises(RuntimeError,match='still active'):resume_campaign(root,execute=True)
        (root/'release').touch()
        deadline=time.monotonic()+10
        while True:
            try:
                with campaign_lock(root):break
            except RuntimeError:
                if time.monotonic()>deadline:raise
                time.sleep(.01)
        resume_campaign(root,execute=True)
        calls=(root/'physical_calls.txt').read_text().splitlines()
        assert calls==['noskills','vanilla','vector','native-gos','goskills-d']
        recovered=json.loads((root/'outcomes/00000.json').read_text())
        assert recovered['recovered_after_controller_exit'] and recovered['status']=='VALID'
    finally:
        if root.exists():(root/'release').touch(exist_ok=True)
        if controller.poll() is None:controller.kill();controller.wait(timeout=5)


def test_relocated_summary_checks_underlying_artifacts(tmp_path):
    import shutil
    from goskills_eval.analysis.summarize_runs import collect
    p=plan(tmp_path);execute_plan(p,fake(p,[]));root=Path(p['output'])
    moved=tmp_path/'archive';shutil.move(root,moved)
    rows,summary=collect(moved)
    assert len(rows)==5 and all(row['score_percent']==0 for row in summary)
    artifact=moved/p['jobs'][0]['output_relative']/'trials/synthetic/result.json'
    artifact.write_text('changed')
    with pytest.raises(ValueError,match='artifact'):collect(moved)


@pytest.mark.parametrize('limits',[{'workers':0},{'workers':21},{'workers':2,'per_method':3},{'workers':True}])
def test_invalid_concurrency_rejected_before_outputs(tmp_path,limits):
    with pytest.raises(ValueError):plan(tmp_path,**limits)
    assert not (tmp_path/'run').exists()
