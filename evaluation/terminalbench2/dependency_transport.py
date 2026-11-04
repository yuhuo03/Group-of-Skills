"""Portable verifier-only transport of frozen public dependency assets."""
import asyncio
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import tempfile

from goskills.io import read_json, write_json
from goskills_eval.terminalbench2 import uv_transport

ROOTS = ('runtime', 'general', 'pmars', 'bookworm')
TARGETS = {'runtime': '/opt/tb2-public-verifier-assets',
           'general': '/opt/tb2-public-dependency-cache',
           'bookworm': '/opt/tb2-public-dependency-cache',
           'pmars': '/opt/tb2-pmars-public-dependency-cache'}
BOOKWORM = {
    'cancel-async-tasks': ('sha256:760c5426807dc80edd6a1b1c3675c197599fc3f9cb46b1a06e7539cb94818553',
                         '79600a6b863def31b4daa008297423010cd2d6243e689d67503e118e4dc53397'),
    'cobol-modernization': ('sha256:14e6e693be70ee0c7f07105dfc0f3cae71fd495cc0106042dd530fc5fbd8e637',
                          '4770437ea96c3cc84684b4f99d55fb148fcac09f9ea1e8ef49de487716e6c334'),
}
PMARS = ('sha256:7b5bae6c1dea946c16c088a0f254182013f7040298420d0021612fe1b1a2e5ee',
         '4770437ea96c3cc84684b4f99d55fb148fcac09f9ea1e8ef49de487716e6c334')


class DependencyPreconditionError(RuntimeError):
    pass


def canonical_path(value):
    path = Path(value).expanduser().absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise DependencyPreconditionError('asset_path_contains_symlink')
    return path.resolve()


def file_sha(path):
    path = Path(path)
    if path.is_symlink() or path.resolve() != path.absolute() or not path.is_file():
        raise DependencyPreconditionError('asset_path_not_regular')
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def catalog():
    return read_json(Path(__file__).with_name('dependency_catalog.json'))


class Assets:
    def __init__(self, config):
        self.config = canonical_path(config)
        file_sha(self.config)
        values = read_json(self.config)
        if not isinstance(values, dict) or set(values) != set(ROOTS):
            raise DependencyPreconditionError('expected_four_asset_roots')
        self.roots = {}
        for name in ROOTS:
            value = values[name]
            if not isinstance(value, str) or not value:
                raise DependencyPreconditionError('invalid_asset_root')
            path = canonical_path(self.config.parent/Path(value).expanduser())
            if not path.is_dir():
                raise DependencyPreconditionError('asset_root_not_regular')
            self.roots[name] = path
        self.catalog = catalog()

    def files(self, name, prefix=None):
        rows = self.catalog[name]['files']
        selected = [row for row in rows if prefix is None or row['path'].startswith(prefix)]
        if not selected:
            raise DependencyPreconditionError('empty_asset_route')
        seen = set()
        for row in selected:
            relative = PurePosixPath(row['path'])
            if (relative.is_absolute() or '..' in relative.parts or '\\' in row['path']
                    or row['path'] != relative.as_posix() or row['path'] in seen):
                raise DependencyPreconditionError('invalid_catalog_path')
            seen.add(row['path'])
            path = self.roots[name]/row['path']
            if file_sha(path) != row['sha256'] or ('bytes' in row and path.stat().st_size != row['bytes']):
                raise DependencyPreconditionError('public_asset_hash_mismatch')
        return selected

    def validate(self):
        counts = {name: len(self.files(name)) for name in ROOTS}
        return {'status': 'VERIFIED', 'asset_files': counts,
                'catalog_sha256': file_sha(Path(__file__).with_name('dependency_catalog.json'))}

    @property
    def archive(self):
        return self.roots['runtime']/'uv/0.9.5/uv-x86_64-unknown-linux-gnu.tar.gz'


def image_identity(reference, name, assets, *, run=subprocess.run):
    matches = [row for row in assets.catalog['images'] if row['task'] == name
               and reference in (row['repo_digest'], row['manifest_digest'], row['original_config_digest'])]
    if len(matches) != 1:
        raise DependencyPreconditionError('image_reference_not_bound')
    row = matches[0]
    result = run(['docker', 'image', 'inspect', '--format', '{{.Descriptor.digest}}', row['repo_digest']],
                 capture_output=True, text=True, timeout=15)
    if result.returncode or result.stdout.strip() != row['manifest_digest']:
        raise DependencyPreconditionError('image_manifest_commitment_mismatch')
    return row['original_config_digest']


async def upload(environment, assets, name, *, prefix=None, target=None):
    rows = assets.files(name, prefix)
    target = target or TARGETS[name]
    with tempfile.TemporaryDirectory(prefix='tb2-public-assets-') as directory:
        stage = Path(directory).resolve()/'files'
        stage.mkdir()
        for row in rows:
            relative = row['path'][len(prefix):] if prefix else row['path']
            dest = stage/relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(assets.roots[name]/row['path'], dest)
            if file_sha(dest) != row['sha256']:
                raise DependencyPreconditionError('asset_changed_during_staging')
            dest.chmod(0o644)
        await asyncio.wait_for(environment.upload_dir(source_dir=stage, target_dir=target), timeout=60)
        quoted = shlex.quote(target)
        command = 'chmod 755 '+quoted+' && find '+quoted+' -type d -exec chmod 755 {} + && find '+quoted+' -type f -exec chmod 644 {} +'
        result = await environment.exec(command, timeout_sec=30)
        if result.return_code != 0:
            raise DependencyPreconditionError('public_asset_mode_normalization_failed')
    return len(rows)


def canonical_report(directory):
    path = Path(directory)/'ctrf.json'
    if not path.is_file():
        raise RuntimeError('canonical_test_report_missing')
    results = read_json(path).get('results', {})
    tests = results.get('tests', [])
    if not tests or results.get('summary', {}).get('tests', 0) != len(tests):
        raise RuntimeError('canonical_tests_not_executed')


def verifier_class(base, assets_config, *, docker_run=subprocess.run):
    assets = Assets(assets_config)
    assets.validate()

    class DependencyVerifier(base):
        async def verify(self):
            _, _, script = self._resolve_tests()
            script = Path(script)
            digest = file_sha(script)
            text = script.read_text()
            task_name = script.parent.parent.name if script.parent.name == 'tests' else None
            original = self.override_env
            overrides = dict(original or {})
            routes = []
            try:
                if task_name in BOOKWORM and digest == BOOKWORM[task_name][1]:
                    identity = image_identity(self.task.config.environment.docker_image, task_name, assets, run=docker_run)
                    if identity == BOOKWORM[task_name][0]:
                        count = await upload(self.environment, assets, 'bookworm')
                        overrides['APT_CONFIG'] = TARGETS['bookworm']+'/apt.conf'
                        routes.append({'route': 'bookworm', 'files': count})
                if task_name == 'build-pmars' and digest == PMARS[1]:
                    identity = image_identity(self.task.config.environment.docker_image, task_name, assets, run=docker_run)
                    if identity == PMARS[0]:
                        count = await upload(self.environment, assets, 'pmars')
                        count += await upload(self.environment, assets, 'general', prefix='wheels/', target=TARGETS['pmars']+'/wheels')
                        overrides.update(APT_CONFIG=TARGETS['pmars']+'/apt.conf', UV_FIND_LINKS=TARGETS['pmars']+'/wheels', UV_NO_INDEX='true')
                        routes.append({'route': 'pmars', 'files': count})
                if 'https://astral.sh/uv/0.9.5/install.sh' in text:
                    count = await upload(self.environment, assets, 'runtime')
                    overrides.update(UV_DOWNLOAD_URL='file://'+TARGETS['runtime']+'/uv/0.9.5',
                                     UV_PYTHON_INSTALL_MIRROR='file://'+TARGETS['runtime']+'/python')
                    routes.append({'route': 'runtime', 'files': count})
                if digest in assets.catalog['general']['eligible_script_sha256']:
                    count = await upload(self.environment, assets, 'general')
                    overrides.update(APT_CONFIG=TARGETS['general']+'/apt.conf', UV_FIND_LINKS=TARGETS['general']+'/wheels', UV_NO_INDEX='true')
                    routes.append({'route': 'general', 'files': count})
                if routes:
                    write_json(Path(self.trial_paths.verifier_dir)/'public_dependency_receipt.json',
                               {'script_sha256': digest, 'routes': routes, 'stage': 'verifier_only_after_agent',
                                'test_script_unchanged': True, 'outer_budget_unchanged': True,
                                'signature_expiry_checks_disabled': False})
                    self.override_env = overrides
                result = await super().verify()
                if '--ctrf /logs/verifier/ctrf.json' in text:
                    canonical_report(self.trial_paths.verifier_dir)
                return result
            finally:
                self.override_env = original

    return uv_transport.verifier_class(DependencyVerifier, assets.archive)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Verify local public dependency asset roots without Docker or APIs')
    parser.add_argument('--config', required=True, type=Path)
    print(json.dumps(Assets(parser.parse_args().config).validate()))


if __name__ == '__main__':
    main()
