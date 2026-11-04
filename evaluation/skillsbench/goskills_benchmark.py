#!/usr/bin/env python3
"""Prepare or execute a fresh SkillsBench task under one of five methods."""
from pathlib import Path
import argparse
import asyncio
import json
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', type=Path)
    parser.add_argument('--config', type=Path, help='Validate a legacy single-trial JSON only; execute fresh tasks with --task')
    parser.add_argument('--method', choices=['noskills', 'vanilla', 'vector', 'native-gos', 'goskills-d'], default='goskills-d')
    for resource in ['skills-root', 'pool', 'workspace', 'upstream']:
        parser.add_argument('--' + resource, type=Path)
    parser.add_argument('--retrieval-python', type=Path, help='Separate GoS virtualenv Python; required for vector/native-gos')
    parser.add_argument('--output', type=Path, required=True)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--prepare-only', action='store_true', help='Write a local task pack/config; no Docker or API calls')
    actions.add_argument('--execute', action='store_true', help='Run one new Docker trial with billable API calls')
    args = parser.parse_args(argv)
    if bool(args.task) == bool(args.config):
        parser.error('Supply exactly one of --task or --config')
    from goskills_eval.utils import load, write, credentials, now
    if args.config:
        if args.execute or args.prepare_only:
            parser.error('--config supports validation only; use --task for a fresh reproducible trial')
        cfg = load(args.config)
        agent = cfg['agent']
        if agent.get('model_name') != 'gpt-5.4' or agent.get('kwargs', {}).get('reasoning_effort') != 'low':
            raise ValueError('Expected GPT-5.4/low prepared configuration')
        print(json.dumps({'status': 'CONFIG_VALIDATED_NOT_EXECUTED', 'task': cfg['task'], 'model': agent['model_name'], 'output': str(args.output)}))
        return 0
    from goskills_eval.skillsbench.task_pack import inspect_inputs, prepare, trial_config
    plan = inspect_inputs(args.task, args.method, args.output, args.skills_root, args.pool, args.workspace, args.upstream, args.retrieval_python)
    if not args.prepare_only and not args.execute:
        print(json.dumps({'status': 'PLAN_ONLY', 'benchmark': 'skillsbench', 'method': args.method,
                          'task': str(args.task), 'output': str(args.output), 'configuration': trial_config(plan)}, indent=2))
        return 0
    if args.prepare_only:
        prepare(plan)
        print(json.dumps({'status': 'PREPARED_NOT_EXECUTED', 'output': str(args.output)}))
        return 0
    credentials()
    # Optional runtime imports begin only after explicit --execute.
    from harbor.models.trial.config import TrialConfig
    from harbor.trial.trial import Trial
    validated = TrialConfig.model_validate(trial_config(plan))
    cfg = prepare(plan)
    receipt = {'status': 'RUNNING', 'benchmark': 'skillsbench', 'method': args.method, 'started_at': now()}
    write(args.output / 'receipt.json', receipt)

    async def run():
        trial = await Trial.create(validated)
        await trial.run()
        return trial

    try:
        trial = asyncio.run(run())
        from goskills_eval.assessment import assess_trial
        evidence = assess_trial(args.output / 'trials' / cfg['trial_name'], args.method, binary=False,
                                require_retrieval=args.method not in {'noskills', 'vanilla'})
        from harbor.environments.docker.docker import _sanitize_docker_compose_project_name
        project = _sanitize_docker_compose_project_name(trial.agent_environment.session_id)
        owned = subprocess.run(['docker', 'ps', '-a', '--filter', 'label=com.docker.compose.project=' + project,
                                '--format', '{{.ID}}'], capture_output=True, text=True, timeout=15)
        if owned.returncode != 0 or owned.stdout.strip():
            raise RuntimeError('owned_containers_not_confirmed_clear')
        receipt.update(status='VALID', owned_containers_clear=True, **evidence)
    except Exception as exc:
        receipt.update(status='PROCESS_FAILED', error_type=type(exc).__name__)
    finally:
        receipt['finished_at'] = now()
        write(args.output / 'receipt.json', receipt)
    print(json.dumps(receipt))
    return 0 if receipt['status'] == 'VALID' else 1


if __name__ == '__main__':
    raise SystemExit(main())
