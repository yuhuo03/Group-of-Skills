"""Split-runtime setup checks; subprocesses are fake or stdlib-only probes."""
from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_doctor',ROOT/'scripts/doctor.py')
doctor=importlib.util.module_from_spec(spec);spec.loader.exec_module(doctor)

def metadata(openai='1.109.1',python=(3,12,12)):
    return {'python':list(python),'packages':{'graph-skills':'0.1.0','alfworld':'0.4.2','textworld':'1.7.0','openai':openai}}

class DoctorTests(unittest.TestCase):
    def test_relative_interpreter_keeps_venv_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'evaluation/configs').mkdir(parents=True);(root/'.venv-retrieval/bin').mkdir(parents=True)
            link=root/'.venv-retrieval/bin/python';link.symlink_to(sys.executable)
            result=doctor.retrieval_interpreter('../../.venv-retrieval/bin/python',root/'evaluation/configs')
            self.assertEqual(str(result),os.path.abspath(link))
            self.assertTrue(result.is_symlink())
            self.assertNotEqual(str(result),str(link.resolve()))

    def test_missing_nonexecutable_and_directory_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);file=root/'not-executable';file.write_text('not a Python interpreter');file.chmod(0o600)
            for value in (None,'',str(root),str(file),str(root/'absent')):
                with self.assertRaises(ValueError):doctor.retrieval_interpreter(value,root)

    def test_probe_is_bounded_and_metadata_only(self):
        response=types.SimpleNamespace(returncode=0,stdout=json.dumps(metadata()))
        with patch.object(doctor.subprocess,'run',return_value=response) as run:
            self.assertEqual(doctor.probe_retrieval_runtime('/local/venv/bin/python'),metadata())
        args,kwargs=run.call_args
        self.assertEqual(args[0][:4],['/local/venv/bin/python','-I','-B','-c'])
        self.assertEqual(kwargs['timeout'],15)
        self.assertNotIn('shell',kwargs)
        self.assertNotIn('import openai',args[0][4])
        self.assertNotIn('os.environ',args[0][4])

    def test_probe_failures_never_echo_subprocess_content(self):
        outcomes=[types.SimpleNamespace(returncode=1,stdout='PRIVATE_DETAIL',stderr='PRIVATE_DETAIL'),
                  types.SimpleNamespace(returncode=0,stdout='PRIVATE_DETAIL'),
                  types.SimpleNamespace(returncode=0,stdout=json.dumps(dict(metadata(),secret='PRIVATE_DETAIL')))]
        for result in outcomes:
            with patch.object(doctor.subprocess,'run',return_value=result):
                with self.assertRaises(ValueError) as error:doctor.probe_retrieval_runtime('/python')
                self.assertNotIn('PRIVATE_DETAIL',str(error.exception))
        with patch.object(doctor.subprocess,'run',side_effect=subprocess.TimeoutExpired('/python',15)):
            with self.assertRaisesRegex(ValueError,'timed out'):doctor.probe_retrieval_runtime('/python')

    def test_split_runtime_checks_separate_package_environments(self):
        rows=[]
        def record(name,ok,detail=None):rows.append({'check':name,'ok':ok,'detail':detail})
        with patch.object(doctor,'retrieval_interpreter',return_value=Path('/venv-retrieval/bin/python')),patch.object(doctor,'probe_retrieval_runtime',return_value=metadata()),patch.object(doctor.importlib.metadata,'version',side_effect=lambda n:{'harbor':'0.20.0','httpx':'0.28.1'}[n]) as current,patch.object(doctor.shutil,'which',return_value='/usr/bin/docker'),patch.object(doctor.sys,'version_info',(3,12,0)),patch.dict(os.environ,{'OPENAI_API_KEY':'private-test-value'}):
            doctor.runtime_checks({'retrieval_python':'../venv-retrieval/bin/python'},ROOT,record)
        self.assertTrue(all(row['ok'] for row in rows))
        self.assertEqual([call.args[0] for call in current.call_args_list],['harbor','httpx'])
        self.assertNotIn('private-test-value',json.dumps(rows))
        checks={r['check']:r for r in rows}
        self.assertEqual(checks['retrieval_package_openai']['detail'],'1.109.1')

    def test_wrong_retrieval_openai_or_python_fails_closed(self):
        for payload in (metadata(openai='2.20.0'),metadata(python=(3,13,0))):
            rows=[]
            with patch.object(doctor,'retrieval_interpreter',return_value=Path('/python')),patch.object(doctor,'probe_retrieval_runtime',return_value=payload),patch.object(doctor.importlib.metadata,'version',side_effect=lambda n:{'harbor':'0.20.0','httpx':'0.28.1'}[n]):
                doctor.runtime_checks({'retrieval_python':'/python'},ROOT,lambda n,o,d=None:rows.append((n,o)))
            checks=dict(rows)
            self.assertFalse(checks['retrieval_package_openai'] and checks['python_for_retrieval'])

    def test_actual_python_probe_does_not_import_optional_runtimes(self):
        # Current interpreter may lack every optional package. That is valid
        # metadata evidence; probe does not attempt to install or import them.
        result=doctor.probe_retrieval_runtime(sys.executable)
        self.assertEqual(result['python'],list(sys.version_info[:3]))
        self.assertEqual(set(result['packages']),set(doctor.RETRIEVAL_PACKAGES)|{'openai'})

if __name__=='__main__':unittest.main()
