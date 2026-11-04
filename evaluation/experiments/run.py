"""Plan/run a resumable benchmark matrix without score retries or overwritten trials."""
from pathlib import Path
import argparse, json, subprocess, sys, re, hashlib, os
from goskills_eval.utils import write, now
from goskills_eval.runtime import resolve_runtime, runtime_cli
from goskills_eval.runtime import METHODS
TRACKS = {'skillsbench': 'skillsbench', 'alfworld': 'alfworld', 'tb2': 'terminalbench2'}
EVALUATION_ROOT = Path(__file__).resolve().parents[1]
RUNNERS = {'alfworld': 'alfworld_run.py', 'skillsbench': 'skillsbench/goskills_benchmark.py', 'tb2': 'terminalbench2/terminalbench2_benchmark.py'}

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

def build_plan(config_path, benchmark, methods, output, tasks=None, *, workers=1, per_method=1):
    config_path=Path(config_path).resolve();base=config_path.parent
    cfg=json.loads(config_path.read_text());output=Path(output).resolve()
    runtime=resolve_runtime(cfg.get("runtime"))
    if output.exists():raise FileExistsError('Use a new campaign output directory')
    if not methods or len(set(methods))!=len(methods) or any(m not in METHODS for m in methods):raise ValueError('Invalid methods')
    tracks=list(TRACKS) if benchmark=='all' else [benchmark]
    if any(t not in TRACKS for t in tracks):raise ValueError('Invalid benchmark')
    if tasks and len(tracks)!=1:raise ValueError('--tasks requires one benchmark')
    from goskills_eval.skill import validate_output
    inputs={'config':config_path}
    for key in ['skills_root','pool','upstream','workspace']:
        if cfg.get(key):inputs[key]=base/Path(cfg[key]).expanduser()
    for track in tracks:
        for key in ['tasks_root','games_manifest','data_root','config']:
            if cfg.get(track,{}).get(key):inputs[track+'_'+key]=base/Path(cfg[track][key]).expanduser()
    validate_output(output,**inputs)
    # Validate every selected method before dispatching any job in the matrix.
    # A later method must not discover a mismatched pool after earlier paid jobs.
    from goskills_eval.skill import validate_resources
    for method in methods:
        validate_resources(method,**{k:inputs.get(k) for k in ['skills_root','pool','workspace','upstream']},check_files=True)
    if 'goskills-d' in methods and set(methods)&{'vector','native-gos'}:
        from goskills_eval.workspace import validate_workspace
        validate_workspace(inputs['workspace'],inputs['skills_root'],pool=inputs['pool'])
    # Preserve the venv executable path: resolving its symlink loses that venv.
    value=cfg.get('retrieval_python')
    retrieval_python=str((base/Path(value).expanduser()).absolute()) if value else sys.executable
    if not Path(retrieval_python).is_file() or not os.access(retrieval_python,os.X_OK):raise ValueError('retrieval_python must be an executable Python path')
    members=json.loads((Path(__file__).parent/'configs/task_ids.json').read_text())
    jobs=[]
    for track in tracks:
        spec=cfg.get(track)
        if not isinstance(spec,dict):raise ValueError('Missing benchmark configuration: '+track)
        selected=tasks or spec.get('tasks') or members[track]
        if not isinstance(selected,list) or not selected or len(set(selected))!=len(selected):raise ValueError('Empty or duplicate tasks')
        asset_config=None
        if track=='tb2' and spec.get('verifier_assets'):
            from goskills_eval.terminalbench2.dependency_transport import Assets
            asset_config=resource(spec,'verifier_assets',base)
            assets=Assets(asset_config);assets.validate()
            validate_output(output,verifier_config=assets.config,**assets.roots)
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
                command=[retrieval_python if track=='alfworld' else sys.executable,str(EVALUATION_ROOT/RUNNERS[track]),'--method',method,'--output',str(dest),*runtime_cli(runtime),*extra]
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
                    if track=='skillsbench':
                        from goskills_eval.skillsbench.task_schema import inspect_task
                        inspect_task(task_path)
                    elif not (task_path/'task.toml').is_file():raise FileNotFoundError(task_path/'task.toml')
                    command+=['--task',str(task_path)]
                    if asset_config is not None:
                        command+=['--verifier-assets',asset_config]
                    if method!='noskills':command+=['--retrieval-python',retrieval_python]
                jobs.append({'benchmark':track,'method':method,'task':task,'output':str(dest),'output_relative':dest.relative_to(output).as_posix(),'command':command})
    from goskills_eval.experiments.bindings import input_bindings,source_bindings
    plan = {'schema_version':2,'status':'PLAN_ONLY','created_at':now(),'config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest(),'output':str(output),'count':len(jobs),'runtime':runtime.to_dict(),'methods':methods,'jobs':jobs,'attempts_per_job':1,'execution':'stop dispatch on failure; drain active runners; no automatic retry',
        'scheduling':{'workers':workers,'per_method':per_method},
        'inputs':input_bindings(jobs,config_path),'sources':source_bindings()}
    from goskills_eval.experiments.scheduler import validate_plan
    validate_plan(plan)
    return plan

from goskills_eval.experiments.scheduler import execute_plan, resume_campaign

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path)
    p.add_argument('--benchmark',choices=[*TRACKS,'all'],default='all')
    p.add_argument('--methods',default='all',help='all or comma-separated method IDs')
    p.add_argument('--tasks',help='comma-separated IDs for one benchmark')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int)
    p.add_argument('--per-method',type=int)
    p.add_argument('--resume',action='store_true',help='Continue only never-dispatched jobs from the saved campaign')
    p.add_argument('--execute',action='store_true',help='Run paid new trials; omitted by default')
    a=p.parse_args()
    if a.resume:
        if a.config or a.tasks or a.benchmark!='all' or a.methods!='all' or a.workers is not None or a.per_method is not None:
            p.error('--resume uses the saved plan; do not supply replacement inputs or scheduling options')
        result=resume_campaign(a.output.resolve(),execute=a.execute)
        if result is not None:print(json.dumps(result,indent=2))
        return
    if not a.config:p.error('--config is required for a new campaign')
    methods=list(METHODS) if a.methods=='all' else a.methods.split(',')
    plan=build_plan(a.config,a.benchmark,methods,a.output,a.tasks.split(',') if a.tasks else None,
                    workers=1 if a.workers is None else a.workers,per_method=1 if a.per_method is None else a.per_method)
    if a.execute:execute_plan(plan)
    else:print(json.dumps(plan,indent=2))
if __name__=='__main__':main()
