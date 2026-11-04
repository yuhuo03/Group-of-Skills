"""Offline transport contracts; synthetic bytes are not real uv runtime tests."""
import asyncio
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from goskills_eval.terminalbench2 import uv_transport as transport


def synthetic_archive(path, *, duplicate=False, link=False, traversal=False):
    with tarfile.open(path, 'w:gz') as tf:
        for name in ('uv', 'uvx', *(['uv'] if duplicate else [])):
            item=tarfile.TarInfo('uv-x86_64-unknown-linux-gnu/'+name)
            payload=b'synthetic binary, not executable test coverage'
            if link and name=='uv':
                item.type=tarfile.SYMTYPE;item.linkname='/etc/passwd';tf.addfile(item)
            else:
                item.size=len(payload);tf.addfile(item,io.BytesIO(payload))
        if traversal:
            item=tarfile.TarInfo('../escaped');item.size=1;tf.addfile(item,io.BytesIO(b'x'))
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MaterializeTests(unittest.TestCase):
    def test_extract_only_regular_members_and_never_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();archive=root/'asset.tar.gz'
            digest=synthetic_archive(archive,traversal=True)
            with patch.object(transport,'ARCHIVE_SHA256',digest):
                result=transport.materialize(archive,root/'bundle')
                self.assertEqual(result['binaries'],['uv','uvx'])
                self.assertEqual(sorted(p.name for p in (root/'bundle').iterdir()),['uv','uvx'])
                self.assertEqual((root/'bundle/uv').stat().st_mode & 0o777,0o755)
                self.assertFalse((root/'escaped').exists())
                with self.assertRaises(FileExistsError):transport.materialize(archive,root/'bundle')

    def test_reject_bad_hash_duplicates_links_and_oversize(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();archive=root/'asset.tar.gz';synthetic_archive(archive)
            with self.assertRaisesRegex(transport.TransportPreconditionError,'hash_mismatch'):
                transport.materialize(archive,root/'bad-hash')
            for mode in ('duplicate','link'):
                digest=synthetic_archive(archive,**{mode:True})
                with patch.object(transport,'ARCHIVE_SHA256',digest):
                    with self.assertRaises(transport.TransportPreconditionError):transport.materialize(archive,root/mode)
                    self.assertFalse((root/mode).exists())
            digest=synthetic_archive(archive)
            with patch.object(transport,'ARCHIVE_SHA256',digest),patch.object(transport,'MAX_BINARY_BYTES',1):
                with self.assertRaises(transport.TransportPreconditionError):transport.materialize(archive,root/'oversize')
            with patch.object(transport,'MAX_ARCHIVE_BYTES',1):
                with self.assertRaisesRegex(transport.TransportPreconditionError,'too_large'):transport.archive_bytes(archive)

    def test_reject_symlink_paths_and_optimized_python_keeps_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();archive=root/'asset.tar.gz';synthetic_archive(archive)
            alias=root/'alias';alias.symlink_to(archive)
            with self.assertRaisesRegex(transport.TransportPreconditionError,'not_regular'):transport.archive_bytes(alias)
            code='from goskills_eval.terminalbench2.uv_transport import archive_bytes; import sys; archive_bytes(sys.argv[1])'
            p=subprocess.run([sys.executable,'-O','-c',code,str(archive)],capture_output=True,text=True,timeout=10)
            self.assertNotEqual(p.returncode,0);self.assertIn('uv_archive_hash_mismatch',p.stderr)


class DownloadTests(unittest.TestCase):
    def test_explicit_download_validates_before_publish_and_refuses_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();source=root/'synthetic.tar.gz'
            digest=synthetic_archive(source);payload=source.read_bytes()
            with patch.object(transport,'ARCHIVE_SHA256',digest),patch.object(transport.urllib.request,'urlopen',side_effect=lambda *a,**k:io.BytesIO(payload)) as network:
                result=transport.download_archive(root/'download.tar.gz')
                self.assertEqual(result['bytes'],len(payload))
                self.assertEqual((root/'download.tar.gz').read_bytes(),payload)
                network.assert_called_once_with(transport.ARCHIVE_URL,timeout=20)
                with self.assertRaises(FileExistsError):transport.download_archive(root/'download.tar.gz')
                self.assertEqual(network.call_count,1)
            with patch.object(transport.urllib.request,'urlopen',return_value=io.BytesIO(b'bad')):
                with self.assertRaisesRegex(transport.TransportPreconditionError,'hash_mismatch'):
                    transport.download_archive(root/'bad.tar.gz')
                self.assertFalse((root/'bad.tar.gz').exists())
            self.assertFalse(list(root.glob('.uv-download-*')))

    def test_download_size_limit_and_publish_race_preserve_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();dest=root/'target.tar.gz'
            with patch.object(transport,'MAX_ARCHIVE_BYTES',1),patch.object(transport.urllib.request,'urlopen',return_value=io.BytesIO(b'large')):
                with self.assertRaisesRegex(transport.TransportPreconditionError,'download_limit'):transport.download_archive(dest)
                self.assertFalse(dest.exists())
            archive=root/'source.tar.gz';digest=synthetic_archive(archive)
            original_link=transport.os.link
            def racing_link(source,target):
                Path(target).write_bytes(b'existing user file')
                return original_link(source,target)
            with patch.object(transport,'ARCHIVE_SHA256',digest),patch.object(transport.urllib.request,'urlopen',return_value=io.BytesIO(archive.read_bytes())),patch.object(transport.os,'link',racing_link):
                with self.assertRaises(FileExistsError):transport.download_archive(dest)
            self.assertEqual(dest.read_bytes(),b'existing user file')
            self.assertFalse(list(root.glob('.uv-download-*')))


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name).resolve();self.script=root/'test.sh';self.script.write_text('synthetic verifier command')
        self.archive=root/'asset.tar.gz';digest=synthetic_archive(self.archive)
        self.enterContext(patch.object(transport,'ARCHIVE_SHA256',digest))
        self.enterContext(patch.object(transport,'SCRIPT_SHA256',{hashlib.sha256(self.script.read_bytes()).hexdigest()}))
        self.events=[];self.failure=None;self.returncode=0;self.env={};self.verifier_env={};self.original={'UNCHANGED':'1'}
        owner=self
        class Environment:
            async def exec(self,command,user):
                owner.events.append(('exec',command,user));return NS(return_code=owner.returncode)
            async def upload_dir(self,source_dir,target_dir):
                owner.events.append(('upload',target_dir,(source_dir/'env').read_text()))
                if owner.failure=='upload':raise RuntimeError('upload failed')
                self.source=source_dir
        class Base:
            def __init__(self):
                self.override_env=owner.original;self.verifier_env=owner.verifier_env
                self.task=NS(config=NS(verifier=NS(env=owner.env)));self.environment=Environment()
            def _resolve_tests(self):return [],owner.script.parent,owner.script
            async def verify(self):
                owner.events.append(('delegate',self.override_env.copy() if self.override_env else None))
                if owner.failure=='delegate':raise RuntimeError('delegate failed')
                if owner.failure=='cancel':raise asyncio.CancelledError()
                return 'original-result'
        self.base=Base

    async def test_success_verifier_only_env_and_restore_original_object(self):
        obj=transport.verifier_class(self.base,self.archive)()
        self.assertEqual(await obj.verify(),'original-result');self.assertIs(obj.override_env,self.original)
        self.assertEqual([e[0] for e in self.events],['exec','upload','exec','delegate'])
        target=self.events[1][1];self.assertRegex(target,r'^/opt/tb2-verifier-uv-[0-9a-f]{32}$')
        self.assertEqual(self.events[1][2],f'export PATH="{target}:$PATH"\nunset BASH_ENV\n')
        self.assertEqual(self.events[-1][1],{'UNCHANGED':'1','BASH_ENV':target+'/env'})
        self.assertFalse(obj.environment.source.exists());self.assertEqual(self.script.read_text(),'synthetic verifier command')

    async def test_unknown_script_is_exact_bypass_even_without_archive(self):
        with patch.object(transport,'SCRIPT_SHA256',set()):
            obj=transport.verifier_class(self.base,Path(self.tmp.name)/'missing')()
            self.assertEqual(await obj.verify(),'original-result')
        self.assertEqual(self.events,[('delegate',self.original)])

    async def test_all_conflict_sources_rejected_before_container_work(self):
        for source in ('env','verifier_env','original'):
            with self.subTest(source=source):
                getattr(self,source)['BASH_ENV']='existing'
                obj=transport.verifier_class(self.base,self.archive)()
                with self.assertRaisesRegex(transport.TransportPreconditionError,'conflict'):await obj.verify()
                del getattr(self,source)['BASH_ENV'];self.assertEqual(self.events,[])

    async def test_preconditions_fail_without_delegate(self):
        self.returncode=1;obj=transport.verifier_class(self.base,self.archive)()
        with self.assertRaisesRegex(transport.TransportPreconditionError,'precondition_failed'):await obj.verify()
        self.assertEqual(len(self.events),1);self.assertIs(obj.override_env,self.original)
        self.events.clear();self.returncode=0;self.failure='upload'
        with self.assertRaises(RuntimeError):await obj.verify()
        self.assertEqual([e[0] for e in self.events],['exec','upload']);self.assertIs(obj.override_env,self.original)

    async def test_delegate_exception_and_cancellation_restore(self):
        for mode,error in [('delegate',RuntimeError),('cancel',asyncio.CancelledError)]:
            self.failure=mode;obj=transport.verifier_class(self.base,self.archive)()
            with self.assertRaises(error):await obj.verify()
            self.assertIs(obj.override_env,self.original)

    async def test_bounded_calls_and_outer_deadline_not_extended(self):
        calls=[];original_wait=asyncio.wait_for
        async def wait(coro,timeout):calls.append(timeout);return await original_wait(coro,timeout)
        with patch.object(transport.asyncio,'wait_for',wait):await transport.verifier_class(self.base,self.archive)().verify()
        self.assertEqual(calls,[20,30,20]);obj=transport.verifier_class(self.base,self.archive)()
        async def slow(**kwargs):await asyncio.sleep(30)
        obj.environment.exec=slow
        with self.assertRaises(asyncio.TimeoutError):await original_wait(obj.verify(),0.01)
        self.assertIs(obj.override_env,self.original)
