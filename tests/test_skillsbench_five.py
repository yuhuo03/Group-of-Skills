"""Fresh taskpack and host-bridge checks; no container/provider imports."""
from pathlib import Path
import asyncio,hashlib,importlib.util,json,os,subprocess,sys,tempfile,types,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'evaluation'))
from goskills_eval.skillsbench.task_pack import METHODS,inspect_inputs,prepare,trial_config,guidance
from goskills_eval.skillsbench.bridge import parse_query_command

def fixtures(root):
 task=root/'task';(task/'environment/skills/oracle').mkdir(parents=True);(task/'tests').mkdir()
 (task/'task.toml').write_text('[agent]\ntimeout_sec=1200\n[environment]\ncpus=1\nmemory_mb=2048\n[verifier]\ntimeout_sec=900\n')
 (task/'instruction.md').write_text('Produce answer.json in the task working directory.\n')
 (task/'environment/Dockerfile').write_text('FROM python:3.12-slim\nCOPY skills /root/skills\nWORKDIR /app\n')
 (task/'environment/skills/oracle/SKILL.md').write_text('Task oracle must not leak\n')
 (task/'tests/test.sh').write_text('echo original-test\n')
 skills=root/'skills';(skills/'example').mkdir(parents=True);(skills/'example/SKILL.md').write_text('# Example\n')
 upstream=root/'upstream';base=upstream/'evaluation/skillsbench'
 graph='This environment contains a prebuilt **Graph of Skills** (GoS) workspace.\n```bash\ngraphskills-query "goal"\n```\nThis command is available on PATH. It queries a prebuilt skill graph and returns a ranked bundle of skills.\nYou must read the retrieval status from that result.\nStatus.\n## Reading the Output\nSource files.\n'
 for name,text in [('_gos_template',graph),('_vectorskills_template','```bash\nOPENAI_API_KEY="test-placeholder" \\\nvectorskills-query "goal"\n```\n'),('_allskills_template','Full filesystem access, no retrieval.\n')]:
  (base/name).mkdir(parents=True);(base/name/'AGENTS.md').write_text(text)
 pool=root/'pool.json';pool.write_text('{}');workspace=root/'index';workspace.mkdir()
 return task,skills,upstream,pool,workspace

class SkillsBenchPackTests(unittest.TestCase):
 def test_all_five_prepare_preserve_tasks_and_originals(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);task,skills,upstream,pool,index=fixtures(r)
   original={f.relative_to(task):f.read_bytes() for f in task.rglob('*') if f.is_file()}
   for method in METHODS:
    out=r/method
    plan=inspect_inputs(task,method,out,skills,pool,index,upstream,sys.executable)
    with patch('goskills_eval.skill.prepare_upstream'):
     cfg=prepare(plan)
    pack=out/'prepared-task'
    self.assertEqual((pack/'task.toml').read_bytes(),original[Path('task.toml')])
    self.assertEqual((pack/'instruction.md').read_bytes(),original[Path('instruction.md')])
    self.assertEqual((pack/'tests/test.sh').read_bytes(),original[Path('tests/test.sh')])
    self.assertFalse((pack/'environment/skills').exists())
    self.assertNotIn('COPY skills',(pack/'environment/Dockerfile').read_text())
    self.assertEqual(cfg['agent']['override_timeout_sec'],900)
    self.assertEqual(cfg['agent']['kwargs']['reasoning_effort'],'low')
    self.assertEqual(cfg['environment']['mounts']==[],method=='noskills')
    self.assertNotIn('override_memory_mb',cfg['environment'])
    self.assertNotIn('verifier',cfg)
    if method=='vanilla':self.assertEqual(cfg['environment']['mounts'][0]['target'],'/opt/skillsbench/skills')
    with self.assertRaises(FileExistsError):prepare(plan)
   self.assertEqual(original,{f.relative_to(task):f.read_bytes() for f in task.rglob('*') if f.is_file()})
 def test_pinned_upstream_checked_before_preparation(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);task,skills,up,pool,index=fixtures(r)
   plan=inspect_inputs(task,'goskills-d',r/'out',skills,pool,index,up)
   with self.assertRaises(ValueError):prepare(plan)
   self.assertFalse((r/'out').exists())

 def test_retrieval_interpreter_is_required_and_venv_symlink_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);task,skills,up,pool,index=fixtures(r)
   with self.assertRaises(ValueError):inspect_inputs(task,'vector',r/'out',skills,pool,index,up)
   interpreter=r/'retrieval-env/bin/python';interpreter.parent.mkdir(parents=True);interpreter.symlink_to(sys.executable)
   plan=inspect_inputs(task,'vector',r/'out',skills,pool,index,up,interpreter)
   self.assertEqual(plan['retrieval_python'],str(interpreter))
   self.assertEqual(trial_config(plan)['agent']['kwargs']['retrieval_python'],str(interpreter))

 def test_no_credentials_in_method_guidance(self):
  with tempfile.TemporaryDirectory() as d:
   _,_,up,_,_=fixtures(Path(d))
   text=guidance('vector',up)
   self.assertNotIn('OPENAI_API_KEY',text);self.assertIn('vectorskills-query "goal"',text)
 def test_ambiguous_copy_and_missing_resources_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);task,skills,up,pool,index=fixtures(r)
   with self.assertRaises(ValueError):inspect_inputs(task,'vector',r/'out',skills,pool,None,up)
   (task/'environment/Dockerfile').write_text('FROM python:3.12\nCOPY ["skills", "/root/skills"]\n')
   with self.assertRaises(ValueError):inspect_inputs(task,'noskills',r/'out')
 def test_cli_all_five_dryrun_no_output_or_provider(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);task,skills,up,pool,index=fixtures(r)
   for m in METHODS:
    out=r/('dry-'+m)
    env=dict(os.environ);env['PYTHONPATH']=str(ROOT)+os.pathsep+str(ROOT/'evaluation')
    result=subprocess.run([sys.executable,str(ROOT/'evaluation/skillsbench/goskills_benchmark.py'),'--method',m,'--task',str(task),'--skills-root',str(skills),'--pool',str(pool),'--workspace',str(index),'--upstream',str(up),'--retrieval-python',sys.executable,'--output',str(out)],env=env,capture_output=True,text=True,timeout=10)
    self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['status'],'PLAN_ONLY');self.assertFalse(out.exists())

 def test_compose_preserved_and_external_context_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);task,skills,up,pool,index=fixtures(r)
   compose=task/'environment/docker-compose.yaml'
   original='services:\n  main:\n    networks: [task-net]\n  api:\n    build: .\nnetworks:\n  task-net: {}\n'
   compose.write_text(original)
   with patch('goskills_eval.skill.prepare_upstream'):
    cfg=prepare(inspect_inputs(task,'vanilla',r/'out',skills,pool,index,up))
   self.assertEqual((r/'out/prepared-task/environment/docker-compose.yaml').read_text(),original)
   self.assertEqual(cfg['environment']['mounts'][0]['read_only'],True)
   compose.rename(task/'environment/docker-compose.yml')
   cfg=prepare(inspect_inputs(task,'noskills',r/'alternate'))
   self.assertEqual((r/'alternate/prepared-task/environment/docker-compose.yaml').read_text(),original)
   (task/'environment/docker-compose.yml').rename(compose)
   compose.write_text('services:\n  api:\n    build: ../../external\n')
   with self.assertRaises(ValueError):inspect_inputs(task,'noskills',r/'bad')

 def test_execute_fake_harbor_uses_fractional_assessment_and_cleanup(self):
  spec=importlib.util.spec_from_file_location('skillsbench_run_under_test',ROOT/'evaluation/skillsbench/goskills_benchmark.py')
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);task,*_=fixtures(r);out=r/'executed'
   class Trial:
    agent_environment=types.SimpleNamespace(session_id='owned-only')
    @classmethod
    async def create(cls,cfg):
     instance=cls();instance.cfg=cfg;return instance
    async def run(self):
     td=Path(self.cfg['trials_dir'])/self.cfg['trial_name'];(td/'agent').mkdir(parents=True);(td/'verifier').mkdir()
     (td/'result.json').write_text(json.dumps({'verifier_result':{'rewards':{'reward':0.5}},'agent_execution':{'started_at':'2026-01-01T00:00:00Z','finished_at':'2026-01-01T00:00:10Z'}}))
     (td/'agent/agent_receipt.json').write_text(json.dumps({'method':'noskills','api_calls':1,'actual_models':['gpt-5.4-2026-03-05'],'transport_fatal':False,'finish_status':'completed','token_usage':{'input':120,'output':30,'cached':10}}))
     (td/'agent/api_calls.json').write_text(json.dumps([{'response':{'model':'gpt-5.4-2026-03-05','usage':{'prompt_tokens':120,'completion_tokens':30,'prompt_tokens_details':{'cached_tokens':10}}}}]))
     (td/'agent/trajectory.json').write_text('{}')
     (td/'verifier/ctrf.json').write_text(json.dumps({'results':{'tests':[{'status':'passed'},{'status':'failed'}],'summary':{'tests':2}}}))
   configmod=types.ModuleType('harbor.models.trial.config');configmod.TrialConfig=types.SimpleNamespace(model_validate=lambda x:x)
   trialmod=types.ModuleType('harbor.trial.trial');trialmod.Trial=Trial
   dockermod=types.ModuleType('harbor.environments.docker.docker');dockermod._sanitize_docker_compose_project_name=lambda x:x
   with patch.dict(sys.modules,{'harbor.models.trial.config':configmod,'harbor.trial.trial':trialmod,'harbor.environments.docker.docker':dockermod}),patch('goskills_eval.utils.credentials',return_value=('offline','offline')),patch.object(module.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout='')) as cleanup:
    self.assertEqual(module.main(['--task',str(task),'--method','noskills','--output',str(out),'--execute']),0)
   receipt=json.loads((out/'receipt.json').read_text());self.assertEqual(receipt['status'],'VALID');self.assertEqual(receipt['reward'],0.5);self.assertEqual(receipt['runtime_seconds'],10);self.assertEqual(receipt['input_tokens'],120)
   self.assertEqual(cleanup.call_args.args[0][4],'label=com.docker.compose.project=owned-only')

class BridgeTests(unittest.TestCase):
 def test_exact_commands_all_retrievers(self):
  for m,c in [('vector','vectorskills-query'),('native-gos','graphskills-query'),('goskills-d','goskills-query')]:
   self.assertEqual(parse_query_command(c+' "visible goal | literal"',m),'visible goal | literal')
  self.assertIsNone(parse_query_command('python3 solution.py','goskills-d'))
 def test_no_shell_prefix_chaining_or_method_substitution(self):
  for text in ['goskills-query "q" | head','cd /app && goskills-query "q"','ENV=x goskills-query "q"','goskills-query "q" > output','goskills-query "q" --top-n 100']:
   with self.assertRaises(ValueError):parse_query_command(text,'goskills-d')
  with self.assertRaises(ValueError):parse_query_command('graphskills-query "q"','noskills')
 def test_quoted_query_is_data(self):
  self.assertEqual(parse_query_command('goskills-query "literal $(not-a-command)"','goskills-d'),'literal $(not-a-command)')

 def test_host_transport_and_container_bash_remain_separate(self):
  fake=types.ModuleType('goskills_eval.harbor_base')
  class Base:
   CLI_FLAGS=[]
   async def _run_bash(self,env,command):return 'container:'+command
  fake.DirectAPIBashAgent=Base;fake.CliFlag=lambda *a,**kw:(a,kw);fake.redact_secret=lambda x:x
  spec=importlib.util.spec_from_file_location('goskills_eval._sb_agent_under_test',ROOT/'evaluation/skillsbench/agents/goskills.py')
  module=importlib.util.module_from_spec(spec)
  with patch.dict(sys.modules,{'goskills_eval.harbor_base':fake}):spec.loader.exec_module(module)
  with tempfile.TemporaryDirectory() as d:
   agent=module.SkillsBenchAgent();agent.logs_dir=Path(d);agent._resolved_flags={'method':'goskills-d','retrieval_python':'/separate/env/bin/python','method_resources':json.dumps({'skills_root':'/read-only/skills','pool':'/host/pool.json'})}
   class Process:
    returncode=0
    async def communicate(self,stdin):
     self.payload=json.loads(stdin);return json.dumps({'status':'PASSED','content':'START: selected skill'}).encode(),b''
   process=Process()
   async def create(*args,**kwargs):
    self.assertNotIn('shell',kwargs);self.assertEqual(args[0],'/separate/env/bin/python');self.assertEqual(args[1:4],('-B','-m','goskills_eval.skillsbench.query'));return process
   with patch.object(module.asyncio,'create_subprocess_exec',side_effect=create):
    observation=asyncio.run(agent._run_bash(None,'goskills-query "goal $(data)"'))
    self.assertIn('START: selected skill',observation);self.assertEqual(process.payload['query'],'goal $(data)');self.assertEqual(agent._successful_retrievals,1)
   self.assertEqual(asyncio.run(agent._run_bash(None,'ls /app')),'container:ls /app')
   self.assertIn('rejected',asyncio.run(agent._run_bash(None,'goskills-query q | head')))

if __name__=='__main__':unittest.main()
