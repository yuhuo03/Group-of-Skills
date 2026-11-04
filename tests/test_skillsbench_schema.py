"""Task layout conversions and all three preflight paths; no runtime calls."""
from pathlib import Path
import importlib.util
import json
import sys

import pytest
from goskills_eval.skillsbench.task_schema import inspect_task, tomllib
from goskills_eval.skillsbench.task_pack import inspect_inputs, prepare, tree
from goskills_eval.experiments.run import build_plan


HEADER = '''schema_version: '1.3'
metadata:
  tags: [parsing, json]
  nested: {literal.key: [1, true, "hello\\nworld"]}
verifier:
  type: test-script
  service: main
  timeout_sec: 900.0
  env: {OFFLINE_FIXTURE: 'true'}
agent:
  timeout_sec: 800.0
environment:
  workdir: /app
  cpus: 2
  memory_mb: 4096
  network_mode: none
solution:
  env: {MODE: synthetic}
'''


def fixture(tmp, header=HEADER):
    task = tmp / 'tasks/sample'
    (task / 'environment').mkdir(parents=True)
    (task / 'environment/Dockerfile').write_text('FROM python:3.12-slim\n')
    (task / 'verifier').mkdir()
    (task / 'verifier/test.sh').write_text('#!/bin/sh\nexit 0\n')
    (task / 'verifier/test.sh').chmod(0o755)
    (task / 'oracle').mkdir()
    (task / 'oracle/solve.sh').write_text('#!/bin/sh\nexit 0\n')
    (task / 'task.md').write_text('---\n' + header + '---\n\nSolve the synthetic task.\n')
    config = tmp / 'config.json'
    config.write_text(json.dumps({'retrieval_python': sys.executable,
                                 'skillsbench': {'tasks_root': 'tasks', 'tasks': ['sample']}}))
    return task, config


def doctor_check(config):
    path = Path(__file__).resolve().parents[1] / 'scripts/doctor.py'
    spec = importlib.util.spec_from_file_location('schema_doctor', path)
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    return next(x for x in doctor.check(config)['checks'] if x['check'] == 'skillsbench_tasks')


def test_same_modern_layout_passes_plan_doctor_and_fresh_preparer(tmp_path):
    task, config = fixture(tmp_path)
    original = tree(task)
    assert doctor_check(config)['ok']
    campaign = build_plan(config, 'skillsbench', ['noskills'], tmp_path / 'campaign')
    assert campaign['count'] == 1
    assert not (tmp_path / 'campaign').exists()
    plan = inspect_inputs(task, 'noskills', tmp_path / 'out')
    cfg = prepare(plan)
    dest = Path(cfg['task']['path'])
    actual = tomllib.loads((dest / 'task.toml').read_text())
    assert actual == plan['normalization']['config']
    assert actual['environment']['network_mode'] == 'no-network'
    assert actual['environment']['workdir'] == '/app'
    assert actual['metadata']['nested']['literal.key'] == [1, True, 'hello\nworld']
    assert actual['verifier']['env'] == {'OFFLINE_FIXTURE': 'true'}
    assert actual['agent']['timeout_sec'] == 800.0
    assert (dest / 'instruction.md').read_text() == 'Solve the synthetic task.\n'
    for old, new in [('verifier/test.sh', 'tests/test.sh'), ('oracle/solve.sh', 'solution/solve.sh')]:
        assert (task / old).read_bytes() == (dest / new).read_bytes()
        assert (task / old).stat().st_mode == (dest / new).stat().st_mode
    assert tree(task) == original
    for name, sha in json.loads((tmp_path / 'out/PREPARATION.json').read_text())['protected_files'].items():
        assert tree(dest)[name] == sha


@pytest.mark.parametrize('header,match', [
    (HEADER.replace("'1.3'", "'1.4'"), 'schema_version'),
    (HEADER + 'new_executor: {}\n', 'Unsupported task.md'),
    (HEADER.replace('  type: test-script', '  type: http'), 'verifier.type'),
    (HEADER.replace('  service: main', '  service: sidecar'), 'verifier.service'),
    (HEADER.replace('  type: test-script', '  hardening: {cleanup_conftests: true}'), 'hardening'),
    (HEADER.replace('  network_mode: none', '  network_mode: restricted'), 'network_mode'),
    (HEADER.replace('  network_mode: none', '  network_mode: none\n  allow_internet: true'), 'not both'),
    (HEADER.replace('  cpus: 2', '  cpus: 2\n  cpus: 4'), 'unique'),
    (HEADER.replace('  workdir: /app', '  workdir: null'), 'preserved'),
    (HEADER.replace("OFFLINE_FIXTURE: 'true'", 'OFFLINE_FIXTURE: true'), 'env values'),
])
def test_unsupported_semantics_rejected_by_all_paths_before_output(tmp_path, header, match):
    task, config = fixture(tmp_path, header)
    with pytest.raises(ValueError, match=match):
        inspect_inputs(task, 'noskills', tmp_path / 'out')
    with pytest.raises(ValueError, match=match):
        build_plan(config, 'skillsbench', ['noskills'], tmp_path / 'campaign')
    assert not doctor_check(config)['ok']
    assert not (tmp_path / 'out').exists() and not (tmp_path / 'campaign').exists()
    assert not (task / 'task.toml').exists()


def test_sandbox_alias_and_allowlist_preserved(tmp_path):
    task, _ = fixture(tmp_path, HEADER.replace('environment:', 'sandbox:').replace(
        'network_mode: none', 'network_mode: allowlist\n  allowed_hosts: [example.test]'))
    config = inspect_task(task)['config']
    assert 'sandbox' not in config
    assert config['environment']['network_mode'] == 'allowlist'
    assert config['environment']['allowed_hosts'] == ['example.test']


def test_conflicting_files_and_source_changes_fail_without_overwrite(tmp_path):
    task, _ = fixture(tmp_path)
    (task / 'tests').mkdir()
    (task / 'tests/test.sh').write_text('different verifier')
    with pytest.raises(ValueError, match='Conflicting'):
        inspect_task(task)
    (task / 'tests/test.sh').write_bytes((task / 'verifier/test.sh').read_bytes())
    plan = inspect_inputs(task, 'noskills', tmp_path / 'out')
    (task / 'verifier/test.sh').write_text('changed after planning')
    with pytest.raises(ValueError, match='changed since planning'):
        prepare(plan)
    assert not (tmp_path / 'out').exists()
    (task / 'task.toml').write_text('version="1.0"')
    with pytest.raises(ValueError, match='Ambiguous'):
        inspect_task(task)


def test_existing_instruction_never_overwritten(tmp_path):
    task, _ = fixture(tmp_path)
    (task / 'instruction.md').write_text('different instruction')
    with pytest.raises(ValueError, match='overwrite instruction'):
        inspect_task(task)
