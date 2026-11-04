"""Exact-script, verifier-only transport of the official uv 0.9.5 binaries.

No dependency on Harbor at import time. The factory wraps the selected verifier
base, so cache transport and canonical report checks can remain in that base.
"""
import asyncio
import hashlib
import io
import os
from pathlib import Path
import tarfile
import tempfile
import time
import urllib.request
import uuid

ARCHIVE_SHA256 = '2cf10babba653310606f8b49876cfb679928669e7ddaa1fb41fb00ce73e64f66'
ARCHIVE_URL = 'https://github.com/astral-sh/uv/releases/download/0.9.5/uv-x86_64-unknown-linux-gnu.tar.gz'
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_BINARY_BYTES = 100 * 1024 * 1024
SCRIPT_SHA256 = frozenset({
    '4770437ea96c3cc84684b4f99d55fb148fcac09f9ea1e8ef49de487716e6c334',
    '404ce42339d0b4df9912282a16f7c875ebc2453d40a9312b671f356208238215',
    '7b4dbbad13e2e71c82f2f6000ac9afbdc0df7916817ebe71272f667a8bf20d04',
    '3b244479776c4ee3639631112799f2cde22cbb80ac10511715e3a8f32909c289',
})


class TransportPreconditionError(RuntimeError):
    """A fixed category, never raw command output or provider content."""


def archive_bytes(archive):
    """Verify the exact official Linux x86_64 archive without network access."""
    path = Path(archive).expanduser().absolute()
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise TransportPreconditionError('uv_archive_not_regular')
    with path.open('rb') as handle:
        data = handle.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise TransportPreconditionError('uv_archive_too_large')
    if hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise TransportPreconditionError('uv_archive_hash_mismatch')
    return data


def materialize(archive, destination):
    """Extract only the two checked regular members into a fresh local directory."""
    data = archive_bytes(archive)
    destination = Path(destination).absolute()
    if destination.parent.resolve() != destination.parent:
        raise TransportPreconditionError('uv_destination_parent_symlink')
    payloads = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tf:
            entries = tf.getmembers()
            for name in ('uv', 'uvx'):
                matches = [item for item in entries
                           if item.name == 'uv-x86_64-unknown-linux-gnu/' + name]
                if len(matches) != 1:
                    raise TransportPreconditionError('uv_archive_member_mismatch')
                member = matches[0]
                if not member.isfile() or not 0 < member.size <= MAX_BINARY_BYTES:
                    raise TransportPreconditionError('uv_archive_member_type_or_size')
                with tf.extractfile(member) as handle:
                    payload = handle.read(MAX_BINARY_BYTES + 1)
                if len(payload) != member.size:
                    raise TransportPreconditionError('uv_archive_member_truncated')
                payloads[name] = payload
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise TransportPreconditionError('uv_archive_invalid') from exc
    destination.mkdir(mode=0o755, exist_ok=False)
    for name, payload in payloads.items():
        with (destination / name).open('xb') as handle:
            handle.write(payload)
        (destination / name).chmod(0o755)
    return {'archive_sha256': ARCHIVE_SHA256, 'binaries': sorted(payloads)}


def download_archive(destination):
    """Explicit public-asset download; never called by planning or verification."""
    destination = Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Use a new archive destination')
    if destination.parent.resolve() != destination.parent:
        raise TransportPreconditionError('uv_destination_parent_symlink')
    started = time.monotonic()
    # Stage beside the destination; link publishes without replacing an existing
    # file even if another downloader wins the race after the initial check.
    with tempfile.TemporaryDirectory(prefix='.uv-download-', dir=destination.parent) as tmp:
        staged = Path(tmp) / 'archive.tar.gz'
        size = 0
        with urllib.request.urlopen(ARCHIVE_URL, timeout=20) as response, staged.open('xb') as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES or time.monotonic() - started > 90:
                    raise TransportPreconditionError('uv_download_limit')
                handle.write(chunk)
        archive_bytes(staged)
        os.link(staged, destination)
    return {'archive_sha256': ARCHIVE_SHA256, 'bytes': size}


async def checked_exec(environment, command):
    result = await asyncio.wait_for(
        environment.exec(command=command, user='root'), timeout=20)
    if type(result.return_code) is not int or result.return_code != 0:
        raise TransportPreconditionError('uv_transport_precondition_failed')


def verifier_class(base, archive):
    """Wrap a verifier; unknown scripts use the original base without any work.

    An outer Harbor verifier deadline still covers this whole coroutine. This
    wrapper neither extends that deadline nor rewrites the task/test commands.
    """
    archive = Path(archive)

    class TransportVerifier(base):
        async def verify(self):
            _, _, script = self._resolve_tests()
            script_sha = hashlib.sha256(script.read_bytes()).hexdigest()
            if script_sha not in SCRIPT_SHA256:
                return await super().verify()
            original = self.override_env
            for config in (self.task.config.verifier.env,
                           self.verifier_env or {}, original or {}):
                if 'BASH_ENV' in config:
                    raise TransportPreconditionError('bash_env_override_conflict')
            target = '/opt/tb2-verifier-uv-' + uuid.uuid4().hex
            with tempfile.TemporaryDirectory(prefix='tb2-uv-transport-') as tmp:
                bundle = Path(tmp).resolve() / 'bundle'
                materialize(archive, bundle)
                with (bundle / 'env').open('x') as handle:
                    handle.write('export PATH="' + target + ':$PATH"\nunset BASH_ENV\n')
                # mkdir refuses an existing target; no agent path is overwritten.
                await checked_exec(self.environment, 'mkdir -m 755 ' + target)
                await asyncio.wait_for(self.environment.upload_dir(
                    source_dir=bundle, target_dir=target), timeout=30)
            check = ('bash --noprofile --norc -c \'source ' + target + '/env; '
                     'test "$(command -v uv)" = ' + target + '/uv && '
                     'test "$(command -v uvx)" = ' + target + '/uvx && '
                     'case "$(uv --version)" in "uv 0.9.5"|"uv 0.9.5 ("*) ;; *) exit 1;; esac && '
                     'case "$(uvx --version)" in "uvx 0.9.5"|"uvx 0.9.5 ("*) ;; *) exit 1;; esac\' >/dev/null 2>&1')
            await checked_exec(self.environment, check)
            self.override_env = {**(original or {}), 'BASH_ENV': target + '/env'}
            try:
                return await super().verify()
            finally:
                self.override_env = original

    return TransportVerifier


def main(argv=None):
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'download'])
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == 'download':
        result = download_archive(args.archive)
    else:
        data = archive_bytes(args.archive)
        result = {'archive_sha256': ARCHIVE_SHA256, 'bytes': len(data)}
    print(json.dumps({'status': 'VERIFIED', **result}))


if __name__ == '__main__':
    main()
