"""Build and assess one TB2 trial without running Docker or a provider."""
from pathlib import Path
import hashlib
import json
import math
import os

from goskills_eval.runtime import METHODS


def trial_config(task, output, method, skills_root=None, agent_timeout_sec=None,
                 *, pool=None, workspace=None, upstream=None, retrieval_python=None, runtime=None, verifier_assets=None):
    from goskills_eval.runtime import resolve_runtime
    runtime = resolve_runtime(runtime)
    if method not in METHODS:
        raise ValueError('Unsupported method')
    if type(agent_timeout_sec) not in (int, float) or not math.isfinite(agent_timeout_sec) or agent_timeout_sec <= 0:
        raise ValueError('Use the task-defined positive agent timeout')
    if method != 'noskills' and not skills_root:
        raise ValueError('skills_root is required')
    if method in ('vector', 'native-gos') and (not workspace or not upstream):
        raise ValueError('workspace and upstream are required for official retrieval')
    if method == 'vanilla' and not upstream:
        raise ValueError('upstream is required for the official all-full catalog')
    if method in ('vanilla', 'vector', 'native-gos') and not retrieval_python:
        raise ValueError('retrieval_python is required for the separate official GoS runtime')
    task, output = Path(task).resolve(), Path(output).resolve()
    mounts = [] if method == 'noskills' else [
        {'type': 'bind', 'source': str(Path(skills_root).resolve()),
         'target': '/opt/graphskills/skills', 'read_only': True}]
    kwargs = {**runtime.agent_kwargs(), 'method': method, 'task_budget_sec': int(agent_timeout_sec)}
    # TB2 command deadlines come from the task, not a per-command override.
    kwargs.pop('tool_timeout_sec')
    for name, value in [('skills_root', skills_root), ('pool', pool),
                        ('workspace', workspace), ('upstream', upstream)]:
        if value is not None:
            kwargs[name] = str(Path(value).resolve())
    if retrieval_python is not None:
        # Resolving a venv's python symlink would discard the selected environment.
        kwargs['retrieval_python'] = os.path.abspath(os.path.expanduser(str(retrieval_python)))
    result = {'task': {'path': str(task)},
            'trial_name': ('gpt54-' if runtime.profile == 'gpt54' else 'trial-') + method + '-' + hashlib.sha256(str(output).encode()).hexdigest()[:10],
            'trials_dir': str(output),
            'agent': {'import_path': 'goskills_eval.terminal_agent:TB2Agent',
                      'model_name': runtime.model, 'kwargs': kwargs},
            'environment': {'type': 'docker', 'delete': True, 'mounts': mounts},
            'timeout_multiplier': 1.0}
    if verifier_assets is not None:
        from goskills_eval.terminalbench2.dependency_transport import Assets
        assets = Assets(verifier_assets)
        assets.validate()
        result['verifier'] = {'import_path': 'goskills_eval.terminalbench2.portable_verifier:PortableVerifier',
                              'kwargs': {'assets_config': str(assets.config)}}
    return result


def validate_inputs(task, output, method, skills_root=None, *, pool=None, workspace=None, upstream=None, retrieval_python=None):
    """Read-only filesystem preflight. No dependency imports, credentials or writes."""
    task, output = Path(task).resolve(), Path(output).resolve()
    if method not in METHODS:
        raise ValueError('Unsupported method')
    if output.exists():
        raise FileExistsError('Output must be a new directory')
    if output == task or task in output.parents or output in task.parents:
        raise ValueError('Output must be outside the benchmark task tree')
    if not (task / 'task.toml').is_file():
        raise FileNotFoundError('task.toml is required')
    if method in ('vanilla', 'vector', 'native-gos') and not retrieval_python:
        raise FileNotFoundError('A separate GoS retrieval Python executable is required')
    if retrieval_python is not None:
        interpreter = Path(os.path.abspath(os.path.expanduser(str(retrieval_python))))
        if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
            raise FileNotFoundError('retrieval_python must be an executable Python path')
    if method == 'noskills':
        return
    if not skills_root or not Path(skills_root).is_dir():
        raise FileNotFoundError('A local skill library is required')
    if not any(Path(skills_root).rglob('SKILL.md')):
        raise ValueError('Skill library contains no SKILL.md')
    if method == 'goskills-d':
        if not pool or not Path(pool).exists():
            raise FileNotFoundError('A JSON or compiled D pool is required')
        from goskills_eval.assets import validate_library
        validate_library(pool, skills_root)
    else:
        if not upstream or not (Path(upstream) / 'gos').is_dir() or not (Path(upstream) / 'evaluation/skill.py').is_file():
            raise FileNotFoundError('The compatible official GoS checkout is required')
        if method in ('vector', 'native-gos') and (not workspace or not Path(workspace).is_dir()):
            raise FileNotFoundError('A matching official GoS workspace is required')
        if method in ('vector', 'native-gos'):
            from goskills_eval.workspace import validate_workspace
            validate_workspace(workspace, skills_root)
    # Neither evidence nor credentials may be saved inside downloaded assets.
    for value in (skills_root, pool, workspace, upstream):
        if value is not None:
            path = Path(value).resolve()
            if output == path or path in output.parents or output in path.parents:
                raise ValueError('Output must be separate from input assets')


# Public compatibility import; shared by SkillsBench with binary=False.
from goskills_eval.assessment import assess_trial
