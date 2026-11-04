import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'evaluation'))
from goskills_eval.campaign import build_plan,execute_plan,METHODS

def script(name):
 s=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

class CampaignTests(unittest.TestCase):
 def fixture(self,tmp):
  tmp=Path(tmp);task=tmp/'tasks'/'sample';task.mkdir(parents=True);(task/'task.toml').write_text('[agent]\ntimeout_sec=300\n')
  data=tmp/'data';data.mkdir();(data/'game.tw-pddl').write_text('synthetic game')
  for x in ['skills','upstream','workspace']:(tmp/x).mkdir()
  (tmp/'pool.json').write_text('{}');(tmp/'base.yaml').write_text('synthetic config')
  (tmp/'games.json').write_text(json.dumps({'000':{'path':'game.tw-pddl'}}))
  cfg={'retrieval_python':sys.executable,'skills_root':'skills','pool':'pool.json','upstream':'upstream','workspace':'workspace','skillsbench':{'tasks_root':'tasks','tasks':['sample']},'tb2':{'tasks_root':'tasks','tasks':['sample']},'alfworld':{'config':'base.yaml','games_manifest':'games.json','data_root':'data','tasks':['000']}}
  file=tmp/'local.json';file.write_text(json.dumps(cfg));return file
 def test_all15_plan_no_outputs_or_execute(self):
  with tempfile.TemporaryDirectory() as d:
   p=build_plan(self.fixture(d),'all',list(METHODS),Path(d)/'run')
   self.assertEqual(p['count'],15);self.assertEqual(len({(j['benchmark'],j['method']) for j in p['jobs']}),15)
   self.assertFalse(Path(p['output']).exists());self.assertTrue(all('--execute' not in j['command'] for j in p['jobs']))
   for j in p['jobs']:
    if j['benchmark']=='alfworld':self.assertIn('--data-root',j['command'])
    if j['benchmark']=='skillsbench' and j['method']=='goskills-d':self.assertIn('--upstream',j['command'])
    if j['benchmark']!='alfworld' and j['method']!='noskills':self.assertIn('--retrieval-python',j['command'])
 def test_stop_on_failed_receipt_no_later_dispatch(self):
  with tempfile.TemporaryDirectory() as d:
   p=build_plan(self.fixture(d),'tb2',list(METHODS),Path(d)/'run');calls=[]
   def fake(cmd,**kw):calls.append(cmd);return SimpleNamespace(returncode=0)
   with self.assertRaises(RuntimeError):execute_plan(p,run_command=fake)
   self.assertEqual(len(calls),1);self.assertEqual(json.loads((Path(d)/'run/STATUS.json').read_text())['status'],'BLOCKED')
 def test_complete_fake_matrix_and_zero_is_valid(self):
  with tempfile.TemporaryDirectory() as d:
   p=build_plan(self.fixture(d),'all',list(METHODS),Path(d)/'run')
   def fake(cmd,**kw):
    dest=Path(cmd[cmd.index('--output')+1]);dest.mkdir(parents=True);(dest/'receipt.json').write_text(json.dumps({'status':'VALID','method':cmd[cmd.index('--method')+1],'reward':0,'input_tokens':10,'output_tokens':2,'runtime_seconds':1.25}));return SimpleNamespace(returncode=0)
   execute_plan(p,run_command=fake);rows,summ=script('summarize_runs').collect(Path(d)/'run')
   self.assertEqual(len(rows),15);self.assertTrue(all(r['score_percent']==0 and r['complete'] for r in summ))
   with self.assertRaises(FileExistsError):execute_plan(p,run_command=fake)
   import shutil
   moved=Path(d)/'moved';shutil.move(str(Path(d)/'run'),moved)
   self.assertEqual(len(script('summarize_runs').collect(moved)[0]),15)
   receipt=moved/p['jobs'][0]['output_relative']/'receipt.json'
   data=json.loads(receipt.read_text());data['reward']=1;receipt.write_text(json.dumps(data))
   with self.assertRaises(ValueError):script('summarize_runs').collect(moved)
 def test_missing_result_does_not_become_zero(self):
  with tempfile.TemporaryDirectory() as d:
   p=build_plan(self.fixture(d),'tb2',['noskills'],Path(d)/'run');Path(p['output']).mkdir();(Path(p['output'])/'PLAN.json').write_text(json.dumps(p))
   rows,summary=script('summarize_runs').collect(p['output']);self.assertIsNone(summary[0]['score_percent']);self.assertEqual(summary[0]['unresolved'],1)
 def test_path_and_duplicates_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   cfg=self.fixture(d)
   with self.assertRaises(ValueError):build_plan(cfg,'tb2',['noskills','noskills'],Path(d)/'out')
   with self.assertRaises(ValueError):build_plan(cfg,'tb2',['noskills'],Path(d)/'out',['../escape'])
   with self.assertRaises(ValueError):build_plan(cfg,'tb2',['noskills'],Path(d)/'tasks'/'new-output')
 def test_safe_asset_extraction_rejects_traversal(self):
  import tarfile,io
  with tempfile.TemporaryDirectory() as d:
   archive=Path(d)/'a.tar.gz'
   with tarfile.open(archive,'w:gz') as t:
    i=tarfile.TarInfo('root/../../escape');i.size=1;t.addfile(i,io.BytesIO(b'x'))
   with self.assertRaises(ValueError):script('fetch_asset').extract(archive,Path(d)/'dest')
 def test_actual_15_cli_plans_from_outside_checkout_without_network(self):
  import subprocess,os
  with tempfile.TemporaryDirectory() as d:
   cfg=self.fixture(d);root=Path(d);task=root/'tasks/sample'
   (task/'instruction.md').write_text('Synthetic task.');(task/'environment').mkdir();(task/'environment/Dockerfile').write_text('FROM python:3.12-slim\n')
   (root/'skills/a').mkdir();(root/'skills/a/SKILL.md').write_text('---\nname: synthetic\ndescription: synthetic\n---\nTest only.\n')
   (root/'upstream/gos').mkdir();(root/'upstream/evaluation').mkdir();(root/'upstream/evaluation/skill.py').write_text('# planning only\n')
   for name in ['_allskills_template','_vectorskills_template','_gos_template']:
    guide=root/'upstream/evaluation/skillsbench'/name;guide.mkdir(parents=True)
    (guide/'AGENTS.md').write_text('You must read the retrieval status from that result.\nstatus\n## Reading the Output\nTest only.\n')
   block=root/'network-block';block.mkdir();(block/'sitecustomize.py').write_text('import socket\ndef forbidden(*args, **kwargs):\n raise AssertionError("Network disabled in plan acceptance")\nsocket.socket.connect=forbidden\nsocket.create_connection=forbidden\n')
   plan=build_plan(cfg,'all',list(METHODS),root/'run')
   environment={'PATH':os.defpath,'PYTHONPATH':str(block),'PYTHONDONTWRITEBYTECODE':'1'}
   for job in plan['jobs']:
    result=subprocess.run(job['command'],cwd=d,env=environment,capture_output=True,text=True,timeout=20)
    self.assertEqual(result.returncode,0,(job['benchmark'],job['method'],result.stderr));self.assertIsInstance(json.loads(result.stdout),dict)
   self.assertFalse((root/'run').exists())
if __name__=='__main__':unittest.main()
