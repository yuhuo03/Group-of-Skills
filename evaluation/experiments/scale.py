"""Validate and prepare matched campaigns for explicitly supplied library sizes."""
import argparse
import json
from pathlib import Path
import shlex
import sys

from goskills.io import read_json
from goskills_eval.experiments.bindings import fingerprint, verify_bindings
from goskills_eval.experiments.run import build_plan, resource
from goskills_eval.experiments.scheduler import durable, sha
from goskills_eval.experiments.skillsets import library_members, member_files
from goskills_eval.runtime import METHODS


def matrix(manifest, output, benchmark, methods, *, workers=1, per_method=1):
    manifest, output = Path(manifest).resolve(strict=True), Path(output).absolute()
    if output.resolve() != output or output.exists():
        raise ValueError('Use a new matrix output path without symlinks')
    spec = read_json(manifest)
    if (set(spec) != {'schema_version', 'membership', 'libraries'} or spec['schema_version'] != 1
            or spec['membership'] not in {'nested', 'independent'}):
        raise ValueError('Invalid scale manifest')
    entries = spec['libraries']
    if not isinstance(entries, list) or not entries:
        raise ValueError('Scale manifest requires libraries')
    sizes, plans, previous, signature = set(), [], None, None
    for entry in entries:
        if (set(entry) != {'size', 'config'} or type(entry['size']) is not int or entry['size'] < 1
                or not isinstance(entry['config'], str) or not entry['config']):
            raise ValueError('Each library requires a positive size and configuration path')
        if entry['size'] in sizes:
            raise ValueError('Duplicate scale size')
        sizes.add(entry['size'])
    for entry in sorted(entries, key=lambda row: row['size']):
        config = (manifest.parent/entry['config']).resolve(strict=True)
        cfg = read_json(config)
        library = Path(resource(cfg, 'skills_root', config.parent))
        members = library_members(library)
        if len(members) != entry['size']:
            raise ValueError('Declared scale differs from actual skill membership')
        identity = {name: member_files(path) for name, path in members.items()}
        if spec['membership'] == 'nested' and previous is not None:
            if any(identity.get(name) != files for name, files in previous.items()):
                raise ValueError('Nested libraries must preserve all smaller-library files')
        previous = identity
        plan = build_plan(config, benchmark, methods, output/f'skills-{entry["size"]}',
                          workers=workers, per_method=per_method)
        # Only library/workspace/pool may vary. The benchmark input bytes and
        # model must match, even when copies live at different absolute paths.
        task_bindings = []
        for job in plan['jobs']:
            cmd = job['command']
            assets = [(flag, fingerprint(cmd[cmd.index(flag)+1]))
                      for flag in ('--task', '--game-file', '--config', '--data-root', '--upstream') if flag in cmd]
            task_bindings.append((job['benchmark'], job['method'], job['task'], assets, cmd[0]))
        current = {'runtime': plan['runtime'], 'jobs': task_bindings}
        if signature is not None and current != signature:
            raise ValueError('Scale campaigns must share model, tasks, harness and interpreter')
        signature = current
        plan['scale'] = {'size': entry['size'], 'membership': spec['membership'],
                         'members_sha256': sha(identity), 'manifest_sha256': fingerprint(manifest)['sha256']}
        plan['inputs'][str(manifest)] = fingerprint(manifest)
        plan['inputs'][str(library)] = fingerprint(library)
        plans.append(plan)
    return {'schema_version': 1, 'kind': 'goskills_scale_matrix', 'status': 'PLAN_ONLY',
            'output': str(output), 'campaigns': plans, 'provider_calls': 0}


def prepare(plan):
    # Preparation never dispatches a trial. Each saved campaign is subsequently
    # executed through the same checked, single-attempt resume entrypoint.
    for campaign in plan['campaigns']:
        verify_bindings(campaign)
    root = Path(plan['output'])
    root.mkdir(parents=True, exist_ok=False)
    durable(root/'MATRIX.json', plan, exclusive=True)
    for campaign in plan['campaigns']:
        target = Path(campaign['output'])
        target.mkdir()
        durable(target/'PLAN.json', campaign, exclusive=True)
        durable(target/'PLAN_BINDING.json', {'plan_sha256': sha(campaign)}, exclusive=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--benchmark', choices=['skillsbench', 'alfworld', 'tb2'], default='skillsbench')
    parser.add_argument('--methods', default='all')
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--per-method', type=int, default=1)
    parser.add_argument('--prepare', action='store_true', help='Save checked plans locally; no API or Docker calls')
    args = parser.parse_args()
    methods = list(METHODS) if args.methods == 'all' else args.methods.split(',')
    plan = matrix(args.manifest, args.output, args.benchmark, methods,
                  workers=args.workers, per_method=args.per_method)
    if args.prepare:
        prepare(plan)
    commands = [shlex.join([sys.executable, '-m', 'goskills_eval.experiments.run',
                            '--resume', '--output', p['output'], '--execute']) for p in plan['campaigns']]
    print(json.dumps({'status': 'PREPARED' if args.prepare else 'PLAN_ONLY',
                      'sizes': [p['scale']['size'] for p in plan['campaigns']],
                      'trials': sum(p['count'] for p in plan['campaigns']),
                      'execute_after_preparation': commands}, indent=2))


if __name__ == '__main__':
    main()
