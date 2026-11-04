"""Five-method TB2 checks using synthetic local assets and fake service objects."""
from goskills.groups import build_pool
from goskills.config import validate_config
from pathlib import Path
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'evaluation'))
from goskills_eval.terminalbench2.config import METHODS, trial_config, validate_inputs, assess_trial
from goskills_eval.query_helper import execute_query
from goskills_eval.assessment import normalize_metrics


class TB2FiveTests(unittest.TestCase):
    def fixture(self, root):
        task = root/'task'; task.mkdir()
        (task/'task.toml').write_text('[agent]\ntimeout_sec = 900\n[environment]\ncpu_count=1\nmemory_mb=2048\n')
        skills=root/'skills'; (skills/'example').mkdir(parents=True)
        (skills/'example/SKILL.md').write_text('---\nname: example\ndescription: synthetic\n---\nSynthetic body')
        upstream=root/'official'; (upstream/'gos').mkdir(parents=True)
        (upstream/'evaluation').mkdir(); (upstream/'evaluation/skill.py').write_text('# synthetic: no import in planning')
        from workspace_fixture import make_workspace
        workspace=root/'index';graph=make_workspace(workspace,skills)
        pool=root/'pool.json';pool.write_text(json.dumps(build_pool(graph,validate_config())))
        return task, skills, upstream, workspace, pool

    def test_five_configurations_preserve_task_resources_and_method_access(self):
        for method in METHODS:
            cfg=trial_config('task','output',method,'skills' if method!='noskills' else None,900,
                             pool='pool.json',workspace='index',upstream='upstream',retrieval_python=sys.executable)
            self.assertEqual(cfg['timeout_multiplier'],1.0)
            self.assertNotIn('verifier',cfg)
            self.assertNotIn('memory_mb',cfg['environment'])
            kw=cfg['agent']['kwargs']
            self.assertEqual((kw['task_budget_sec'],kw['max_turns'],kw['max_completion_tokens']), (900,60,4096))
            self.assertEqual(kw['reasoning_effort'],'low')
            self.assertEqual(kw['retrieval_python'],os.path.abspath(sys.executable))
            self.assertEqual(len(cfg['environment']['mounts']),0 if method=='noskills' else 1)

    def test_all_five_cli_plans_need_no_credentials_or_optional_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,skills,upstream,index,pool=self.fixture(root)
            env={k:v for k,v in os.environ.items() if 'KEY' not in k and 'TOKEN' not in k}
            env['PYTHONPATH']=str(ROOT)+os.pathsep+str(ROOT/'evaluation')
            for method in METHODS:
                output=root/('out-'+method)
                result=subprocess.run([sys.executable,str(ROOT/'evaluation/terminalbench2/terminalbench2_benchmark.py'),
                    '--task',str(task),'--method',method,'--skills-root',str(skills),'--pool',str(pool),
                    '--workspace',str(index),'--upstream',str(upstream),'--retrieval-python',sys.executable,'--output',str(output)],
                    env=env,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout)['agent']['kwargs']['method'],method)
                self.assertFalse(output.exists())

    def test_preflight_rejects_missing_resources_and_existing_output(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,skills,upstream,index,pool=self.fixture(root)
            with self.assertRaises(FileNotFoundError):validate_inputs(task,root/'new','goskills-d',skills)
            with self.assertRaises(FileNotFoundError):validate_inputs(task,root/'new','vector',skills,upstream=upstream)
            with self.assertRaises(FileExistsError):validate_inputs(task,skills,'noskills')
            with self.assertRaises(ValueError):validate_inputs(task,task/'output','noskills')

    def test_separate_interpreter_required_and_venv_symlink_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,skills,upstream,index,pool=self.fixture(root)
            for method in ('vanilla','vector','native-gos'):
                with self.assertRaisesRegex(FileNotFoundError,'separate GoS'):
                    validate_inputs(task,root/'output',method,skills,upstream=upstream,workspace=index)
            python=root/'venv/bin/python';python.parent.mkdir(parents=True);python.symlink_to(sys.executable)
            validate_inputs(task,root/'output','vector',skills,upstream=upstream,workspace=index,retrieval_python=python)
            cfg=trial_config(task,root/'output','vector',skills,900,upstream=upstream,workspace=index,retrieval_python=python)
            self.assertEqual(cfg['agent']['kwargs']['retrieval_python'],str(python))
            self.assertNotEqual(str(python),str(python.resolve()))
            with self.assertRaises(FileNotFoundError):
                validate_inputs(task,root/'output','vector',skills,upstream=upstream,workspace=index,retrieval_python=root/'missing-python')

    def test_helper_subprocess_uses_selected_interpreter_and_d_default(self):
        import goskills_eval
        fake=types.ModuleType('goskills_eval.harbor_base')
        fake.DirectAPIBashAgent=type('Base',(),{'CLI_FLAGS':[]});fake.CliFlag=lambda *a,**k:object()
        commands=[]
        class Process:
            pid=999999999;returncode=0
            async def communicate(self,body):
                self.payload=json.loads(body)
                return json.dumps({'status':'PASSED','content':'synthetic context'}).encode(),None
        async def spawn(*args,**kwargs):commands.append(args);return Process()
        with patch.dict(sys.modules,{'goskills_eval.harbor_base':fake,'httpx':types.ModuleType('httpx')}),patch.object(goskills_eval,'harbor_base',fake,create=True):
            spec=importlib.util.spec_from_file_location('goskills_eval._tb2_python_test',ROOT/'evaluation/terminal_agent.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as d,patch.object(module.asyncio,'create_subprocess_exec',spawn):
                for method in ('vanilla','vector','native-gos','goskills-d'):
                    agent=module.TB2Agent();agent._resolved_flags={'method':method}
                    expected=sys.executable if method=='goskills-d' else '/synthetic/retrieval-venv/bin/python'
                    if method!='goskills-d':agent._resolved_flags['retrieval_python']=expected
                    agent.logs_dir=Path(d)/method;agent.logs_dir.mkdir();agent.retrieval_count=agent.successful_retrievals=0
                    self.assertEqual(asyncio.run(agent.retrieve('visible query')),'synthetic context')
                    self.assertEqual(commands[-1][0],expected)
                    self.assertEqual(commands[-1][1:],('-B','-m','goskills_eval.query_helper'))

    def test_isolated_helper_dispatches_all_methods_and_resources(self):
        calls=[]
        def fake(method, query, directory, **resources):
            calls.append((method,query,resources))
            (directory/'bundle.json').write_text('{}')
            return 'synthetic contract'
        with tempfile.TemporaryDirectory() as d:
            for method in METHODS:
                code,result=execute_query({'method':method,'query':'visible query','directory':str(Path(d)/method),
                     'pool':'pool','skills_root':'skills','workspace':'index','upstream':'official'},fake)
                self.assertEqual(code,0); self.assertEqual(result['status'],'PASSED')
                self.assertEqual(calls[-1][0],method)
                self.assertEqual(calls[-1][2]['workspace'],'index')
                self.assertNotIn('content',json.loads((Path(d)/method/'receipt.json').read_text()))

    def test_helper_failure_does_not_return_raw_error_or_valid_zero(self):
        def failed(*a,**k):raise RuntimeError('sensitive-response-content')
        with tempfile.TemporaryDirectory() as d:
            code,result=execute_query({'method':'vector','query':'q','directory':str(Path(d)/'new')},failed)
            self.assertEqual(code,1);self.assertEqual(result['status'],'FAILED')
            self.assertNotIn('reward',result);self.assertNotIn('sensitive-response-content',json.dumps(result))

    def test_vanilla_is_full_catalog_but_retrieval_methods_are_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            for method in ['vanilla','vector','native-gos','goskills-d']:
                code,result=execute_query({'method':method,'query':'q','directory':str(Path(d)/method)},lambda *a,**k:'x'*9001)
                self.assertEqual(code,0 if method=='vanilla' else 1)

    def test_terminal_tool_routes_keep_vanilla_and_noskills_bash_only(self):
        import goskills_eval
        fake=types.ModuleType('goskills_eval.harbor_base')
        class Base:
            CLI_FLAGS=[]
            def _tools(self):return [{'function':{'name':'bash','description':'base'}}]
        fake.DirectAPIBashAgent=Base;fake.CliFlag=lambda *a,**k:object()
        httpx=types.ModuleType('httpx')
        path=ROOT/'evaluation/terminal_agent.py'
        with patch.dict(sys.modules,{'goskills_eval.harbor_base':fake,'httpx':httpx}),patch.object(goskills_eval,'harbor_base',fake,create=True):
            spec=importlib.util.spec_from_file_location('goskills_eval._tb2_test',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            for method in METHODS:
                agent=module.TB2Agent();agent._resolved_flags={'method':method}
                names=[t['function']['name'] for t in agent._tools()]
                self.assertEqual(names,['bash'] if method in ['noskills','vanilla'] else ['bash','retrieve_skills'])

    def test_full_terminal_loop_all_five_with_fake_chat_and_retrieval(self):
        import goskills_eval
        fake=types.ModuleType('goskills_eval.harbor_base')
        class Base:
            CLI_FLAGS=[]
            def _append_user_step(self,text):pass
            def _append_agent_step(self,*a,**k):pass
            def _record_usage(self,d):return None
            def populate_context_post_run(self,context):pass
        fake.DirectAPIBashAgent=Base;fake.CliFlag=lambda *a,**k:object();fake.redact_secret=lambda x:x
        with patch.dict(sys.modules,{'goskills_eval.harbor_base':fake,'httpx':types.ModuleType('httpx')}),patch.object(goskills_eval,'harbor_base',fake,create=True):
            spec=importlib.util.spec_from_file_location('goskills_eval._tb2_loop_test',ROOT/'evaluation/terminal_agent.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as tmp:
                for method in METHODS:
                    agent=module.TB2Agent();agent._resolved_flags={'method':method,'task_budget_sec':900}
                    agent.logs_dir=Path(tmp)/method;agent.model_name='gpt-5.4';agent._max_turns=1
                    agent._turn_count=agent._tool_call_count=agent._input_tokens=agent._output_tokens=agent._cache_tokens=0
                    agent._steps=[];agent._api_calls=[]
                    async def retrieval(query):
                        agent.retrieval_count+=1;agent.successful_retrievals+=1
                        return 'synthetic '+method+' context'
                    async def chat(messages):
                        result={'model':'gpt-5.4-2026-03-05','choices':[{'message':{'content':'done'}}]}
                        agent._api_calls.append({'response':result});return result
                    agent.retrieve=retrieval;agent._chat_completion=chat
                    asyncio.run(agent.run('visible task',None,None))
                    receipt=json.loads((agent.logs_dir/'agent_receipt.json').read_text())
                    self.assertEqual(receipt['finish_status'],'completed')
                    self.assertEqual(receipt['retrieval_count'],0 if method=='noskills' else 1)
                    self.assertEqual(agent.messages[0]['role'],'system')
                    self.assertIn('Terminal-Bench',agent.messages[0]['content'])
                    self.assertNotIn('SkillsBench',agent.messages[0]['content'])

    def evidence(self,td):
        (td/'agent').mkdir();(td/'verifier').mkdir()
        result={'agent_execution':{'started_at':'2026-01-01T00:00:00+00:00','finished_at':'2026-01-01T00:00:02+00:00'},'verifier_result':{'rewards':{'reward':0}}}
        receipt={'method':'noskills','api_calls':1,'actual_models':['gpt-5.4-2026-03-05'],'transport_fatal':False,'finish_status':'completed','token_usage':{'input':10,'output':2,'cached':3}}
        (td/'result.json').write_text(json.dumps(result));(td/'agent/agent_receipt.json').write_text(json.dumps(receipt))
        (td/'agent/api_calls.json').write_text(json.dumps([{'response':{'model':'gpt-5.4-2026-03-05','usage':{'prompt_tokens':10,'completion_tokens':2,'prompt_tokens_details':{'cached_tokens':3}}}}]))
        (td/'agent/trajectory.json').write_text('{}')
        (td/'verifier/ctrf.json').write_text(json.dumps({'results':{'tests':[{'status':'failed'}],'summary':{'tests':1}}}))
        return result

    def test_real_zero_evidence_kept_but_missing_reports_or_null_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            td=Path(d);result=self.evidence(td)
            checked=assess_trial(td,'noskills')
            self.assertEqual((checked['reward'],checked['runtime_seconds'],checked['input_tokens']),(0,2,10))
            result['verifier_result']['rewards']['reward']=None
            (td/'result.json').write_text(json.dumps(result))
            with self.assertRaises(ValueError):assess_trial(td,'noskills')
            result['verifier_result']['rewards']['reward']=0
            (td/'result.json').write_text(json.dumps(result));(td/'verifier/ctrf.json').unlink()
            with self.assertRaises(FileNotFoundError):assess_trial(td,'noskills')

    def test_runner_requires_cleanup_before_accepting_valid_zero(self):
        from goskills_eval.terminalbench2 import cleanup
        from test_tb2_cleanup import Docker, PROJECT
        spec=importlib.util.spec_from_file_location('tb2_cleanup_runner',ROOT/'evaluation/terminalbench2/terminalbench2_benchmark.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        original_cleanup=cleanup.reconcile_trial
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,*_=self.fixture(root);docker=Docker()
            owner=self
            class Trial:
                agent_environment=types.SimpleNamespace(session_id=PROJECT)
                @classmethod
                async def create(cls,cfg):obj=cls();obj.cfg=cfg;return obj
                async def run(self):
                    td=Path(self.cfg['trials_dir'])/self.cfg['trial_name'];td.mkdir()
                    owner.evidence(td)
            configmod=types.ModuleType('harbor.models.trial.config');configmod.TrialConfig=types.SimpleNamespace(model_validate=lambda x:x)
            trialmod=types.ModuleType('harbor.trial.trial');trialmod.Trial=Trial
            dockermod=types.ModuleType('harbor.environments.docker.docker');dockermod._sanitize_docker_compose_project_name=lambda x:x
            def hook(project,path):
                return original_cleanup(project,path,run=docker,clock=lambda:0,sleep=lambda _:None)
            with patch.dict(sys.modules,{'harbor.models.trial.config':configmod,'harbor.trial.trial':trialmod,'harbor.environments.docker.docker':dockermod}),patch('goskills_eval.utils.credentials',return_value=('offline','offline')),patch.object(cleanup,'reconcile_trial',side_effect=hook),patch.object(module.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout='')):
                code=module.main(['--task',str(task),'--method','noskills','--output',str(root/'out'),'--execute'])
                self.assertTrue(docker.removed)
                from test_tb2_cleanup import CID
                docker=Docker([cleanup.stopped(PROJECT,CID)|{'status':'running','running':True,'pid':123}])
                failed=module.main(['--task',str(task),'--method','noskills','--output',str(root/'refused'),'--execute'])
                refused_removed=docker.removed
                docker=Docker()
                with patch('goskills_eval.terminalbench2.config.assess_trial',side_effect=ValueError('synthetic invalid report')):
                    invalid=module.main(['--task',str(task),'--method','noskills','--output',str(root/'invalid'),'--execute'])
                self.assertTrue(docker.removed)
                invalid_receipt=json.loads((root/'invalid/receipt.json').read_text())
                self.assertEqual((invalid,invalid_receipt['status'],invalid_receipt['owned_containers_clear']),(1,'PROCESS_FAILED',True))
            self.assertEqual(code,0);self.assertEqual(failed,1);self.assertFalse(refused_removed)
            receipt=json.loads((root/'out/receipt.json').read_text())
            self.assertEqual((receipt['status'],receipt['reward']),('VALID',0))
            self.assertTrue(json.loads((root/'out/cleanup_receipt.json').read_text())['owned_clear'])
            self.assertEqual(json.loads((root/'refused/receipt.json').read_text())['status'],'PROCESS_FAILED')
            result=next((root/'refused').glob('gpt54-*/result.json'))
            self.assertEqual(json.loads(result.read_text())['verifier_result']['rewards']['reward'],0)

    def test_metrics_do_not_fabricate_missing_runtime_or_tokens(self):
        with self.assertRaises(ValueError):normalize_metrics({}, {})
        with self.assertRaises(ValueError):normalize_metrics({}, {'token_usage':{'input':10,'output':2}})


if __name__=='__main__':unittest.main()
