"""Synthetic result artifacts for scheduler tests, never benchmark scores."""
import hashlib
import json
from pathlib import Path


def complete(job,runtime,*,reward=0,failed=False,clear=True):
    root=Path(job['output']);root.mkdir(parents=True,exist_ok=False)
    receipt={'status':'PROCESS_FAILED' if failed else 'VALID','method':job['method'],
             'runtime':runtime,'reward':reward,'input_tokens':10,'output_tokens':2,'runtime_seconds':1.25}
    receipt['environment_closed' if job['benchmark']=='alfworld' else 'owned_containers_clear']=clear
    def artifact(path,value):
        path.parent.mkdir(parents=True,exist_ok=True);raw=json.dumps(value).encode();path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()
    if not failed:
        if job['benchmark']=='alfworld':
            receipt['result_sha256']=artifact(root/'result.json',{'reward':reward})
            receipt['api_calls_sha256']=artifact(root/'api_calls.json',[])
        else:
            trial=root/'trials/synthetic'
            artifact(root/'trial_config.json',{'trials_dir':str(root/'trials'),'trial_name':'synthetic','agent':{'model_name':runtime['model']}})
            receipt['result_sha256']=artifact(trial/'result.json',{'reward':reward})
            receipt['trace_sha256']=artifact(trial/'agent/trajectory.json',{'synthetic':True})
    artifact(root/'receipt.json',receipt)
    return receipt
