"""Offline adapter tests: no simulator, Docker or provider calls."""
from pathlib import Path
import copy,json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'evaluation'))
from goskills_eval.terminal_config import trial_config
from goskills_eval.source_gate import validate_frozen_sources
from goskills_eval.retrieval import DContext
from goskills.groups import build_pool
from goskills.config import canonical_hash,validate_config

class EvaluationTests(unittest.TestCase):
 def test_task_resource_and_model_semantics(self):
  cfg=trial_config('task','output','goskills-d','skills',900)
  self.assertEqual(cfg['timeout_multiplier'],1.0)
  self.assertEqual(cfg['agent']['kwargs']['task_budget_sec'],900)
  self.assertEqual(cfg['agent']['kwargs']['reasoning_effort'],'low')
  self.assertEqual(cfg['agent']['kwargs']['max_completion_tokens'],4096)
  self.assertTrue(cfg['environment']['mounts'][0]['read_only'])
  self.assertNotIn('memory_mb',cfg['environment'])
  self.assertNotIn('verifier',cfg)  # Do not overwrite benchmark scoring.
 def test_bad_scope_is_rejected(self):
  with self.assertRaises(ValueError):trial_config('a','b','unknown','skills',900)
  with self.assertRaises(ValueError):trial_config('a','b','goskills-d',None,900)
  with self.assertRaises(ValueError):trial_config('a','b','noskills',None,0)
 def test_source_fidelity_and_arbitrary_root(self):
  graph=json.loads((Path(__file__).resolve().parents[1]/'examples/minimal_graph.json').read_text())
  pool=build_pool(graph,validate_config(None))
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'pool.json';p.write_text(json.dumps(pool));ctx=DContext(p,'/mounted/skills')
   b=ctx.query('clean csv schema verify')
   validate_frozen_sources(b,ctx.retriever.pool,ctx.pool_hash,'/mounted/skills')
   self.assertTrue(b['presented_skills'])
   bad=copy.deepcopy(b);bad['presented_skills'][0]['body']+=' forged'
   with self.assertRaises(ValueError):validate_frozen_sources(bad,ctx.retriever.pool,ctx.pool_hash,'/mounted/skills')
 def test_blank_endpoint_falls_back(self):
  import os
  from unittest.mock import patch
  from goskills_eval.common import credentials
  with patch.dict(os.environ,{'OPENAI_API_KEY':'offline-synthetic','OPENAI_BASE_URL':''}):
   self.assertEqual(credentials()[1],'https://api.openai.com/v1')
 def test_output_not_overwritten(self):
  from goskills_eval.common import write
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'result.json';write(p,{'reward':0},True)
   with self.assertRaises(FileExistsError):write(p,{'reward':1},True)
   self.assertEqual(json.loads(p.read_text())['reward'],0)
class EntrypointTests(unittest.TestCase):
 def run_script(self,track,args):
  import subprocess,os
  root=Path(__file__).resolve().parents[1]
  env=dict(os.environ);env['PYTHONPATH']=str(root)+os.pathsep+str(root/'evaluation')
  return subprocess.run([sys.executable,str(root/'evaluation'/track/'run.py'),*args],capture_output=True,text=True,env=env,timeout=20)
 def test_help_without_provider_or_simulator(self):
  for track in ['alfworld','skillsbench','terminalbench2']:
   result=self.run_script(track,['--help']);self.assertEqual(result.returncode,0,result.stderr)
 def test_sb_prepared_config_dryrun(self):
  with tempfile.TemporaryDirectory() as tmp:
   tmp=Path(tmp);config=tmp/'config.json';out=tmp/'new-output'
   config.write_text(json.dumps({'task':{'path':'prepared-task'},'agent':{'model_name':'gpt-5.4','kwargs':{'reasoning_effort':'low'}}}))
   result=self.run_script('skillsbench',['--config',str(config),'--output',str(out)])
   self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['status'],'CONFIG_VALIDATED_NOT_EXECUTED');self.assertFalse(out.exists())
 def test_tb2_dryrun_uses_task_deadline(self):
  with tempfile.TemporaryDirectory() as tmp:
   tmp=Path(tmp);task=tmp/'task';task.mkdir();out=tmp/'new-output'
   (task/'task.toml').write_text('[agent]\ntimeout_sec = 900\n')
   result=self.run_script('terminalbench2',['--task',str(task),'--method','noskills','--output',str(out)])
   self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['agent']['kwargs']['task_budget_sec'],900);self.assertFalse(out.exists())
 def test_alf_plan_does_not_load_upstream(self):
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp)/'new-output'
   result=self.run_script('alfworld',['--upstream','absent-upstream','--config','absent.yaml','--game-file','absent.tw-pddl','--skills-root','absent-skills','--method','noskills','--output',str(out)])
   self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['status'],'PLAN_ONLY');self.assertFalse(out.exists())

if __name__=='__main__':unittest.main()
