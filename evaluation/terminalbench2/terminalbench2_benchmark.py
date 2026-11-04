#!/usr/bin/env python3
"""Plan or execute one new TB2 trial with any of the five recorded methods."""
from pathlib import Path
import argparse
import asyncio
import json
import sys
import subprocess


def main(argv=None):
    from goskills_eval.terminalbench2.config import METHODS, trial_config, validate_inputs, assess_trial
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--method', choices=METHODS, default='goskills-d')
    parser.add_argument('--skills-root', type=Path)
    parser.add_argument('--pool', type=Path)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--upstream', type=Path)
    parser.add_argument('--retrieval-python', type=Path, help='Python executable in the separate GoS environment; required for vanilla/vector/native-gos')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', help='Run one Docker trial with billable API calls; otherwise validate and print configuration')
    from goskills_eval.runtime import add_runtime_arguments, runtime_from_args
    add_runtime_arguments(parser)
    args = parser.parse_args(argv)
    runtime = runtime_from_args(args)
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    resources = {'pool': args.pool, 'workspace': args.workspace, 'upstream': args.upstream,
                 'retrieval_python': args.retrieval_python}
    validate_inputs(args.task, args.output, args.method, args.skills_root, **resources)
    task = tomllib.loads((args.task / 'task.toml').read_text())
    config = trial_config(args.task, args.output, args.method, args.skills_root,
                          task['agent']['timeout_sec'], runtime=runtime, **resources)
    if not args.execute:
        print(json.dumps(config, indent=2))
        return 0
    from goskills_eval.utils import credentials, write, now
    credentials()
    # Model/simulator imports occur only beyond the explicit execution boundary.
    from harbor.models.trial.config import TrialConfig
    from harbor.trial.trial import Trial
    validated = TrialConfig.model_validate(config)
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    write(args.output / 'trial_config.json', config, True)
    receipt = {'status': 'RUNNING', 'method': args.method, 'started_at': now(), 'runtime': runtime.to_dict()}
    write(args.output / 'receipt.json', receipt)
    trial = None
    async def run():
        nonlocal trial
        trial = await Trial.create(validated)
        await trial.run()
        return trial
    try:
        trial = asyncio.run(run())
        evidence = assess_trial(args.output / config['trial_name'], args.method, runtime=runtime)
        receipt.update(status='VALID', **evidence)
    except Exception as exc:
        receipt.update(status='PROCESS_FAILED', error_type=type(exc).__name__)
    finally:
        receipt['owned_containers_clear'] = False
        if trial is not None:
            try:
                from harbor.environments.docker.docker import _sanitize_docker_compose_project_name
                project = _sanitize_docker_compose_project_name(trial.agent_environment.session_id)
                from goskills_eval.terminalbench2.cleanup import reconcile_trial
                cleanup = reconcile_trial(project, args.output / 'cleanup_observation.jsonl')
                write(args.output / 'cleanup_receipt.json', cleanup, True)
                owned = subprocess.run(['docker', 'ps', '-a', '--filter',
                                        'label=com.docker.compose.project=' + project,
                                        '--format', '{{.ID}}'], capture_output=True, text=True, timeout=15)
                if owned.returncode != 0 or owned.stdout.strip():
                    raise RuntimeError('owned_containers_not_confirmed_clear')
                receipt['owned_containers_clear'] = True
            except Exception as exc:
                receipt.update(status='PROCESS_FAILED', cleanup_error_type=type(exc).__name__)
        receipt['finished_at'] = now()
        write(args.output / 'receipt.json', receipt)
    print(json.dumps(receipt))
    return 0 if receipt['status'] == 'VALID' else 1


if __name__ == '__main__':
    raise SystemExit(main())
