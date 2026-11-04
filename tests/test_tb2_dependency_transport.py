import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as S

import pytest

from goskills_eval.terminalbench2 import dependency_transport as transport


def setup(tmp_path, monkeypatch, *, body='echo synthetic', name='sample'):
    definitions = {}
    roots = {}
    for kind in transport.ROOTS:
        root = tmp_path/kind
        root.mkdir()
        names = ['apt.conf', 'apt.sources', 'apt/packages'] if kind != 'runtime' else ['uv/test', 'python/test']
        if kind == 'general':
            names += ['wheels/a.whl']
        records = []
        for item in names:
            path = root/item
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'public fixture')
            records.append({'path': item, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size})
        definitions[kind] = {'files': records, 'eligible_script_sha256': []}
        roots[kind] = kind
    definitions['images'] = []
    monkeypatch.setattr(transport, 'catalog', lambda: definitions)
    config = tmp_path/'assets.json'
    config.write_text(json.dumps(roots))
    script = tmp_path/'tasks'/name/'tests/test.sh'
    script.parent.mkdir(parents=True)
    script.write_text(body)
    output = tmp_path/'verifier'
    output.mkdir()
    calls = []

    class Environment:
        async def upload_dir(self, source_dir, target_dir):
            calls.append(('upload', target_dir, sorted(p.relative_to(source_dir).as_posix() for p in Path(source_dir).rglob('*') if p.is_file())))
        async def exec(self, command, timeout_sec):
            calls.append(('exec', command, timeout_sec))
            return S(return_code=0)

    class Base:
        def __init__(self):
            self.environment = Environment()
            self.override_env = {'KEEP': 'fixture'}
            self.verifier_env = {}
            self.task = S(config=S(environment=S(docker_image='fixture-image'), verifier=S(env={})))
            self.trial_paths = S(verifier_dir=output)
            self.fail = False
        def _resolve_tests(self):
            return None, None, script
        async def verify(self):
            calls.append(('delegate', dict(self.override_env)))
            if self.fail:
                raise RuntimeError('fixture-failure')
            return 'synthetic-result'
    return config, script, definitions, calls, Base


def test_unknown_script_delegates_without_upload_or_override_change(tmp_path, monkeypatch):
    config, _, _, calls, base = setup(tmp_path, monkeypatch)
    obj = transport.verifier_class(base, config)()
    original = obj.override_env
    assert asyncio.run(obj.verify()) == 'synthetic-result'
    assert calls == [('delegate', {'KEEP': 'fixture'})]
    assert obj.override_env is original


@pytest.mark.parametrize('fail', [False, True])
def test_runtime_and_general_routes_keep_modes_scoring_and_restore(tmp_path, monkeypatch, fail):
    config, script, cat, calls, base = setup(tmp_path, monkeypatch, body='https://astral.sh/uv/0.9.5/install.sh')
    cat['general']['eligible_script_sha256'] = [transport.file_sha(script)]
    obj = transport.verifier_class(base, config)()
    original = obj.override_env
    obj.fail = fail
    if fail:
        with pytest.raises(RuntimeError, match='fixture-failure'):
            asyncio.run(obj.verify())
    else:
        assert asyncio.run(obj.verify()) == 'synthetic-result'
    assert obj.override_env is original
    env = next(c[1] for c in calls if c[0] == 'delegate')
    assert env['UV_NO_INDEX'] == 'true' and env['KEEP'] == 'fixture'
    assert env['UV_DOWNLOAD_URL'].startswith('file:///opt/')
    assert [c[1] for c in calls if c[0] == 'upload'] == [transport.TARGETS['runtime'], transport.TARGETS['general']]
    assert len([c for c in calls if c[0] == 'exec' and '-type f -exec chmod 644' in c[1]]) == 2


def test_bookworm_image_binding_and_task_script_gate(tmp_path, monkeypatch):
    config, script, cat, calls, base = setup(tmp_path, monkeypatch, name='cobol-modernization')
    identity = transport.BOOKWORM['cobol-modernization'][0]
    monkeypatch.setattr(transport, 'BOOKWORM', {'cobol-modernization': (identity, transport.file_sha(script))})
    cat['images'] = [{'task': 'cobol-modernization', 'original_config_digest': identity,
                      'manifest_digest': 'sha256:manifest', 'repo_digest': 'fixture-image'}]
    docker = []
    def inspect(command, **kwargs):
        docker.append(command)
        return S(returncode=0, stdout='sha256:manifest\n')
    obj = transport.verifier_class(base, config, docker_run=inspect)()
    asyncio.run(obj.verify())
    assert docker[0][-2:] == ['{{.Descriptor.digest}}', 'fixture-image']
    assert next(c[1] for c in calls if c[0] == 'delegate')['APT_CONFIG'] == transport.TARGETS['bookworm']+'/apt.conf'


@pytest.mark.parametrize('descriptor', ['mismatch', 'sha256:manifest'])
def test_pmars_original_manifest_binding_and_reused_wheels(tmp_path, monkeypatch, descriptor):
    config, script, cat, calls, base = setup(tmp_path, monkeypatch, name='build-pmars')
    monkeypatch.setattr(transport, 'PMARS', (transport.PMARS[0], transport.file_sha(script)))
    cat['images'] = [{'task': 'build-pmars', 'original_config_digest': transport.PMARS[0],
                      'manifest_digest': 'sha256:manifest', 'repo_digest': 'fixture-image'}]
    def inspect(command, **kwargs):
        assert command[-2:] == ['{{.Descriptor.digest}}', 'fixture-image']
        return S(returncode=0, stdout=descriptor)
    obj = transport.verifier_class(base, config, docker_run=inspect)()
    if descriptor == 'mismatch':
        with pytest.raises(transport.DependencyPreconditionError, match='manifest_commitment_mismatch'):
            asyncio.run(obj.verify())
        assert not calls
    else:
        asyncio.run(obj.verify())
        uploads = [c for c in calls if c[0] == 'upload']
        assert len(uploads) == 2 and uploads[-1][2] == ['a.whl']


def test_bad_asset_refused_before_any_delegate(tmp_path, monkeypatch):
    config, _, _, calls, base = setup(tmp_path, monkeypatch)
    (tmp_path/'general/apt.conf').write_text('modified')
    with pytest.raises(transport.DependencyPreconditionError, match='hash_mismatch'):
        transport.verifier_class(base, config)
    assert not calls


def test_canonical_missing_is_not_zero_and_overrides_restored(tmp_path, monkeypatch):
    config, _, _, calls, base = setup(tmp_path, monkeypatch, body='pytest --ctrf /logs/verifier/ctrf.json')
    obj = transport.verifier_class(base, config)()
    original = obj.override_env
    with pytest.raises(RuntimeError, match='canonical_test_report_missing'):
        asyncio.run(obj.verify())
    assert obj.override_env is original


def test_permission_failure_never_delegates(tmp_path, monkeypatch):
    config, script, cat, calls, base = setup(tmp_path, monkeypatch)
    cat['general']['eligible_script_sha256'] = [transport.file_sha(script)]
    obj = transport.verifier_class(base, config)()
    async def fail(*args, **kwargs):
        return S(return_code=1)
    obj.environment.exec = fail
    with pytest.raises(transport.DependencyPreconditionError, match='mode_normalization'):
        asyncio.run(obj.verify())
    assert not any(c[0] == 'delegate' for c in calls)


def test_asset_roots_relative_parents_and_symlink_rejection(tmp_path, monkeypatch):
    config, _, _, _, _ = setup(tmp_path, monkeypatch)
    nested = tmp_path/'nested'
    nested.mkdir()
    config2 = nested/'assets.json'
    config2.write_text(json.dumps({name: '../'+name for name in transport.ROOTS}))
    assert transport.Assets(config2).validate()['status'] == 'VERIFIED'
    (tmp_path/'general/apt.conf').unlink()
    (tmp_path/'general/apt.conf').symlink_to(tmp_path/'pmars/apt.conf')
    with pytest.raises(transport.DependencyPreconditionError):
        transport.Assets(config2).validate()


def test_cancellation_restores_original_environment(tmp_path, monkeypatch):
    config, _, _, calls, base = setup(tmp_path, monkeypatch, body='https://astral.sh/uv/0.9.5/install.sh')
    async def cancel(self):
        assert 'UV_DOWNLOAD_URL' in self.override_env
        raise asyncio.CancelledError
    base.verify = cancel
    obj = transport.verifier_class(base, config)()
    original = obj.override_env
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(obj.verify())
    assert obj.override_env is original


def test_asset_bundle_copies_only_catalogued_inputs(tmp_path, monkeypatch):
    from goskills_eval.terminalbench2.asset_bundle import export_assets
    config, _, _, _, _ = setup(tmp_path, monkeypatch)
    (tmp_path/'general'/'unrelated.txt').write_text('not an input')
    output = tmp_path/'export'
    result = export_assets(config, output)
    assert result['status'] == 'VERIFIED'
    assert not (output/'general/unrelated.txt').exists()
    assert json.loads((output/'assets.json').read_text()) == {k: k for k in transport.ROOTS}
    with pytest.raises(FileExistsError):
        export_assets(config, output)
    with pytest.raises(ValueError, match='separate'):
        export_assets(config, tmp_path/'general/child')


def test_campaign_binds_only_catalogued_assets_and_detects_change(tmp_path, monkeypatch):
    from goskills_eval.experiments.bindings import input_bindings, verify_bindings
    config, _, _, _, _ = setup(tmp_path, monkeypatch)
    (tmp_path/'general'/'unrelated.txt').write_text('not an input')
    jobs=[{'command':['python','runner','--verifier-assets',str(config)]}]
    binding=input_bindings(jobs,config)
    assert not any('unrelated' in key for key in binding)
    plan={'inputs':binding,'sources':{str(config):binding[str(config)]}}
    verify_bindings(plan)
    (tmp_path/'general/apt.conf').write_text('changed')
    with pytest.raises(ValueError, match='inputs changed'):
        verify_bindings(plan)


def test_trial_config_enables_factory_explicitly(tmp_path, monkeypatch):
    from goskills_eval.terminalbench2.config import trial_config
    config, script, _, _, _ = setup(tmp_path, monkeypatch)
    output=tmp_path/'new-trial'
    original=trial_config(script.parent.parent,output,'noskills',agent_timeout_sec=900)
    bound=trial_config(script.parent.parent,output,'noskills',agent_timeout_sec=900,verifier_assets=config)
    assert 'verifier' not in original
    verifier=bound.pop('verifier')
    assert bound==original
    assert verifier['kwargs']['assets_config']==str(config)
    assert verifier['import_path'].endswith(':PortableVerifier')
