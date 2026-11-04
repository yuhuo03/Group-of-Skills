#!/usr/bin/env python3
"""Plan or run exactly one ALFWorld episode with any of the five recorded methods."""
from pathlib import Path
import argparse
import os
import sys
import json
import math
from goskills_eval.skill import METHODS, validate_resources, validate_output


def resolve_game(args):
    if args.game_file:
        return args.game_file.resolve(), None
    if args.game_index is None or not args.games_manifest:
        raise ValueError('Use --game-file or --game-index with --games-manifest')
    data = json.loads(args.games_manifest.read_text())
    if 'tasks' in data:
        matches = [row for row in data['tasks'] if row['index'] == args.game_index]
    else:
        matches = [row for key, row in data.items() if key.isdigit() and int(key) == args.game_index]
    if len(matches) != 1:
        raise ValueError('The manifest must contain exactly one selected game index')
    row = matches[0]
    path = Path(row.get('path', row.get('gamefile', row.get('game_file', ''))))
    if not str(path) or str(path) == '.':
        raise ValueError('Missing game file in manifest')
    root = (args.data_root or args.games_manifest.parent).resolve()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError('Manifest game file must remain within the selected data root')
    return path, row.get('sha256', row.get('game_sha256'))


def normalized_metrics(result):
    usage = result['token_usage']
    inp, out = usage['prompt_tokens'], usage['completion_tokens']
    seconds = result['agent_runtime_seconds']
    if type(inp) is not int or inp <= 0 or type(out) is not int or out < 0:
        raise ValueError('invalid selected agent token counts')
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError('invalid selected agent runtime')
    return {'input_tokens': inp, 'output_tokens': out, 'runtime_seconds': seconds}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--upstream', type=Path, required=True)
    p.add_argument('--config', type=Path, required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--game-file', type=Path)
    group.add_argument('--game-index', type=int)
    p.add_argument('--games-manifest', type=Path)
    p.add_argument('--data-root', type=Path)
    p.add_argument('--skills-root', type=Path)
    p.add_argument('--pool', type=Path)
    p.add_argument('--workspace', type=Path)
    p.add_argument('--method', choices=METHODS, default='goskills-d')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--execute', action='store_true', help='Run one billable simulator episode; default prints plan')
    a = p.parse_args()
    try:
        validate_resources(a.method, skills_root=a.skills_root, pool=a.pool, workspace=a.workspace, upstream=a.upstream)
        game_path, expected_game_sha = resolve_game(a)
        validate_output(a.output, skills_root=a.skills_root, pool=a.pool, workspace=a.workspace,
                        upstream=a.upstream, config=a.config, games_manifest=a.games_manifest,
                        data_root=a.data_root, game_file=game_path)
    except ValueError as exc:
        p.error(str(exc))
    if not a.execute:
        print(json.dumps({'status': 'PLAN_ONLY', 'method': a.method, 'game_file': str(game_path),
                          'output': str(a.output), 'seed': 42, 'max_steps': 30,
                          'model': 'gpt-5.4', 'reasoning_effort': 'low'}))
        return
    from goskills_eval.utils import credentials, write, sha, now
    from goskills_eval.skill import prepare_upstream
    validate_resources(a.method, skills_root=a.skills_root, pool=a.pool, workspace=a.workspace, upstream=a.upstream, check_files=True)
    if a.output.exists():
        raise FileExistsError('Choose a new output directory')
    if expected_game_sha and sha(game_path) != expected_game_sha:
        raise ValueError('game file does not match its manifest hash')
    key, base = credentials()
    os.environ.update(API_KEY=key, BASE_URL=base)
    if a.data_root:
        os.environ['ALFWORLD_DATA'] = str(a.data_root.resolve())
    prepare_upstream(a.upstream)
    import yaml
    import evaluation.alfworld_run as upstream
    from evaluation.skill import SkillModule
    from alfworld.agents.environment import get_environment
    from goskills_eval.alfworld.adapter import make
    from goskills_eval.alfworld.chat import Chat
    config = yaml.safe_load(a.config.read_text())
    config['general']['random_seed'] = 42
    config['general']['use_cuda'] = False
    a.output.mkdir(parents=True, exist_ok=False)
    env = None
    receipt = {'status': 'RUNNING', 'method': a.method, 'started_at': now(),
               'game_sha256': sha(game_path), 'config_sha256': sha(a.config),
               'upstream_runner_sha256': sha(Path(upstream.__file__)),
               'model': 'gpt-5.4', 'max_steps': 30, 'seed': 42}
    write(a.output/'receipt.json', receipt)
    try:
        e = get_environment('AlfredTWEnv')(config, train_eval='eval_out_of_distribution')
        game = str(game_path)
        if game not in e.game_files:
            raise ValueError('game file is outside the official out-of-distribution split')
        e.game_files = [game]
        env = e.init_env(batch_size=1)
        env.seed(42)
        obs, info = env.reset()
        if str(info['extra.gamefile'][0]) != game:
            raise ValueError('environment game identity mismatch')
        ob = '\n'.join(obs[0].split('\n\n')[1:])
        name = '/'.join(game.split('/')[-3:-1])
        skill = make(a.method, SkillModule, a.output, skills_root=a.skills_root, pool=a.pool,
                     workspace=a.workspace, upstream=a.upstream)
        chat = Chat(a.output, upstream)
        upstream.llm = chat
        result = upstream.alfworld_run_single(env=env, obs=[ob], names=[name], max_steps=30,
                                             model='gpt-5.4', Skill_Module=skill)[0]
        write(a.output/'result.json', result, True)
        if chat.failed or not chat.calls or len(chat.calls) != result['steps']:
            raise ValueError('incomplete agent trace')
        if result['reward'] not in (0, 1, False, True):
            raise ValueError('invalid reward')
        receipt.update(normalized_metrics(result))
        receipt.update(status='VALID', reward=int(result['reward']), result_sha256=sha(a.output/'result.json'),
                       api_calls_sha256=sha(a.output/'api_calls.json'))
    except Exception as exc:
        receipt.update(status='PROCESS_FAILED', error_type=type(exc).__name__)
        raise
    finally:
        if env is not None:
            try:
                env.close()
                receipt['environment_closed'] = True
            except Exception as exc:
                receipt.update(status='PROCESS_FAILED', cleanup_error_type=type(exc).__name__)
        receipt['finished_at'] = now()
        write(a.output/'receipt.json', receipt)
    print(json.dumps(receipt))
    if receipt['status'] != 'VALID':
        raise SystemExit(1)

if __name__ == '__main__':
    main()
