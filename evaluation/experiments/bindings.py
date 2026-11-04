"""Read-only source/input and result bindings for a saved campaign."""
import hashlib
import json
import math
from pathlib import Path
from goskills_eval.runtime import resolve_runtime

IGNORED = {'.git', '__pycache__', '.pytest_cache', '.venv', 'venv'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('Expected a regular evidence file')
    h=hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def fingerprint(path):
    path=Path(path)
    if path.is_symlink():raise ValueError('Input binding cannot follow symlinks')
    if path.is_file():return {'kind':'file','sha256':file_digest(path)}
    if not path.is_dir():raise FileNotFoundError(path)
    h=hashlib.sha256();count=0
    def walk(directory):
        nonlocal count
        for item in sorted(directory.iterdir()):
            if item.name in IGNORED or item.name.endswith(('.pyc','.pyo')) or (item.name.startswith('.env') and item.name!='.env.example'):continue
            if item.is_symlink():raise ValueError('Input binding cannot follow symlinks')
            if item.is_dir():walk(item)
            elif item.is_file():
                row=[item.relative_to(path).as_posix(),file_digest(item)]
                h.update(json.dumps(row,ensure_ascii=False,separators=(',',':')).encode()+b'\n');count+=1
            else:raise ValueError('Unsupported input file type')
    walk(path)
    return {'kind':'tree','files':count,'sha256':h.hexdigest()}


def input_bindings(jobs, config_path):
    paths={str(Path(config_path).resolve())}
    flags={'--skills-root','--pool','--workspace','--upstream','--task','--game-file','--config','--data-root','--verifier-assets'}
    for job in jobs:
        command=job['command']
        for i,value in enumerate(command):
            if value in flags:
                selected=Path(command[i+1]).resolve();paths.add(str(selected))
                if value=='--workspace':
                    from goskills_eval.workspace import identity_path
                    paths.add(str(identity_path(selected)))
                if value=='--verifier-assets':
                    from goskills_eval.terminalbench2.dependency_transport import Assets
                    assets=Assets(selected)
                    paths.update(str(assets.roots[name]/row['path'])
                                 for name in assets.roots for row in assets.files(name))
    # Hash a directory only once when it already contains a selected child.
    roots=[]
    for value in sorted(paths,key=lambda value:(len(Path(value).parts),value)):
        path=Path(value)
        if any(parent.is_dir() and path.is_relative_to(parent) for parent in roots):continue
        roots.append(path)
    return {str(path):fingerprint(path) for path in roots}


def source_bindings():
    import goskills
    roots=[Path(__file__).resolve().parents[1],Path(goskills.__file__).resolve().parent]
    return {str(path):fingerprint(path) for path in roots}


def verify_bindings(plan):
    for field in ('inputs','sources'):
        if not isinstance(plan.get(field),dict) or not plan[field]:raise ValueError('Missing campaign '+field+' bindings')
        for path,expected in plan[field].items():
            if fingerprint(path)!=expected:raise ValueError('Campaign '+field+' changed: '+path)


def receipt_evidence(plan, job):
    """Check terminal receipt, cleanup, metrics, and exact referenced artifacts."""
    root=Path(job['output']);path=root/'receipt.json'
    if root.is_symlink() or path.resolve()!=path.absolute():raise ValueError('Receipt path contains a symlink')
    raw=path.read_bytes();receipt=json.loads(raw)
    if receipt.get('method')!=job['method'] or receipt.get('runtime')!=plan['runtime']:
        raise ValueError('Receipt identity or runtime mismatch')
    if receipt.get('status') not in {'VALID','PROCESS_FAILED'}:raise ValueError('Trial receipt is not terminal')
    clear=receipt.get('environment_closed') is True if job['benchmark']=='alfworld' else receipt.get('owned_containers_clear') is True
    artifacts={}
    if receipt['status']=='VALID':
        if not clear:raise ValueError('Valid receipt lacks resource clearance')
        for key in ('reward','input_tokens','output_tokens','runtime_seconds'):
            value=receipt.get(key)
            if type(value) not in (int,float) or not math.isfinite(value) or value<0:raise ValueError('Invalid receipt metric')
            if key.endswith('_tokens') and type(value) is not int:raise ValueError('Noninteger token count')
        if receipt['reward']>1 or (job['benchmark']!='skillsbench' and receipt['reward'] not in (0,1)):
            raise ValueError('Invalid reward')
        if job['benchmark']=='alfworld':
            files={'result_sha256':root/'result.json','api_calls_sha256':root/'api_calls.json'}
        else:
            config_path=root/'trial_config.json';config=json.loads(config_path.read_text())
            trial_name=config['trial_name']
            if not isinstance(trial_name,str) or Path(trial_name).name!=trial_name or trial_name in {'','.','..'}:raise ValueError('Invalid trial name')
            trial_root=(Path(config['trials_dir'])/trial_name).resolve()
            if not trial_root.is_relative_to(root.resolve()):raise ValueError('Trial artifacts escape campaign')
            if config['agent']['model_name']!=resolve_runtime(plan['runtime']).model:raise ValueError('Trial model mismatch')
            artifacts['trial_config.json']=file_digest(config_path)
            files={'result_sha256':trial_root/'result.json','trace_sha256':trial_root/'agent/trajectory.json'}
        for field,artifact in files.items():
            if artifact.resolve()!=artifact.absolute():raise ValueError('Artifact path contains a symlink')
            actual=file_digest(artifact)
            if receipt.get(field)!=actual:raise ValueError('Result artifact changed or missing hash')
            artifacts[artifact.relative_to(root).as_posix()]=actual
    return {'receipt_sha256':digest(raw),'artifacts':artifacts,'valid':receipt['status']=='VALID','resources_clear':clear}
