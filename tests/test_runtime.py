"""Model configuration and request-path checks without provider calls."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import patch

import pytest
from goskills_eval.runtime import (resolve_runtime, runtime_cli, runtime_from_args,
                                  add_runtime_arguments, TERMINAL_SETTINGS)
from goskills_eval.terminalbench2.config import trial_config
from goskills_eval.skillsbench.task_pack import trial_config as sb_config
from goskills_eval.assessment import assess_trial

ROOT=Path(__file__).resolve().parents[1]
CUSTOM=dict(profile='custom',model='example-chat',expected_model='example-chat-2026',
            reasoning_effort=None,completion_token_field='max_tokens')


def test_pinned_profile_and_explicit_custom_cli():
    pinned=resolve_runtime()
    assert pinned.model=='gpt-5.4' and pinned.expected_model=='gpt-5.4-2026-03-05'
    assert pinned.reasoning_effort=='low' and pinned.agent_kwargs()['max_completion_tokens']==4096
    parser=argparse.ArgumentParser();add_runtime_arguments(parser)
    for runtime in [pinned,resolve_runtime(CUSTOM)]:
        assert runtime_from_args(parser.parse_args(runtime_cli(runtime)))==runtime
    with pytest.raises(ValueError,match='custom'):
        runtime_from_args(parser.parse_args(['--model','other']))
    with pytest.raises(ValueError):runtime_from_args(parser.parse_args(['--profile','custom']))
    with pytest.raises(ValueError):resolve_runtime({**pinned.to_dict(),'model':'other'})
    for change in [dict(extra='bad'),dict(reasoning_effort=[]),dict(completion_token_field='wrong'),dict(expected_model=''),dict(model='secret\nvalue')]:
        with pytest.raises(ValueError):resolve_runtime({**CUSTOM,**change})


@pytest.mark.parametrize('method',['noskills','vanilla','vector','native-gos','goskills-d'])
def test_custom_configs_change_model_only_not_method_or_budgets(method):
    kwargs=dict(skills_root='skills',pool='pool',workspace='workspace',upstream='gos',retrieval_python=sys.executable)
    pinned=trial_config('task','out',method,agent_timeout_sec=900,**kwargs)
    custom=trial_config('task','out',method,agent_timeout_sec=900,runtime=CUSTOM,**kwargs)
    assert custom['agent']['model_name']==CUSTOM['model']
    assert custom['agent']['kwargs']['expected_model']==CUSTOM['expected_model']
    assert custom['agent']['kwargs']['reasoning_effort']==''
    assert custom['agent']['kwargs']['completion_token_field']=='max_tokens'
    for field in ['environment','timeout_multiplier','task']:assert pinned[field]==custom[field]
    for field in ['max_turns','max_completion_tokens','max_observation_chars','task_budget_sec']:
        assert pinned['agent']['kwargs'][field]==custom['agent']['kwargs'][field]
    plan=dict(output='out',method=method,resources={'skills_root':'skills'},runtime=CUSTOM)
    sb=sb_config(plan)
    assert sb['agent']['model_name']==CUSTOM['model']
    assert sb['agent']['override_timeout_sec']==900 and sb['agent']['override_setup_timeout_sec']==180
    for key,value in TERMINAL_SETTINGS.items():assert sb['agent']['kwargs'][key]==value


def test_custom_assessment_accepts_only_the_expected_response_model(tmp_path):
    from test_tb2_five import TB2FiveTests
    TB2FiveTests().evidence(tmp_path)
    receipt=tmp_path/'agent/agent_receipt.json';data=json.loads(receipt.read_text())
    data['actual_models']=[CUSTOM['expected_model']];receipt.write_text(json.dumps(data))
    calls=tmp_path/'agent/api_calls.json';data=json.loads(calls.read_text())
    data[0]['response']['model']=CUSTOM['expected_model'];calls.write_text(json.dumps(data))
    checked=assess_trial(tmp_path,'noskills',runtime=CUSTOM)
    assert checked['reward']==0 and checked['actual_model']==CUSTOM['expected_model']
    with pytest.raises(ValueError,match='model'):assess_trial(tmp_path,'noskills')
    data[0]['response']['model']='wrong';calls.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='evidence'):assess_trial(tmp_path,'noskills',runtime=CUSTOM)


def test_all15_custom_campaign_plans_match_without_network(tmp_path):
    import os
    from test_campaign import CampaignTests
    from goskills_eval.experiments.run import build_plan, METHODS
    cfg=CampaignTests().fixture(tmp_path);data=json.loads(cfg.read_text());data['runtime']=CUSTOM;cfg.write_text(json.dumps(data))
    task=tmp_path/'tasks/sample';(task/'environment').mkdir();(task/'environment/Dockerfile').write_text('FROM python:3.12-slim\n')
    (tmp_path/'upstream/gos').mkdir();(tmp_path/'upstream/evaluation').mkdir();(tmp_path/'upstream/evaluation/skill.py').write_text('# plan fixture')
    for name in ['_allskills_template','_vectorskills_template','_gos_template']:
        p=tmp_path/'upstream/evaluation/skillsbench'/name;p.mkdir(parents=True)
        (p/'AGENTS.md').write_text('You must read the retrieval status from that result.\nstatus\n## Reading the Output\n')
    blocked=tmp_path/'blocked';blocked.mkdir()
    (blocked/'sitecustomize.py').write_text('import socket\ndef no(*a,**k): raise AssertionError("offline")\nsocket.create_connection=no\nsocket.socket.connect=no\n')
    plan=build_plan(cfg,'all',list(METHODS),tmp_path/'run')
    assert plan['runtime']==CUSTOM and plan['count']==15
    for job in plan['jobs']:
        result=subprocess.run(job['command'],cwd=tmp_path,env={'PATH':os.defpath,'PYTHONPATH':str(blocked)},capture_output=True,text=True,timeout=15)
        assert result.returncode==0,result.stderr
        data=json.loads(result.stdout)
        agent=data.get('agent',data.get('configuration',{}).get('agent'))
        if agent:assert agent['model_name']==CUSTOM['model'] and agent['kwargs']['expected_model']==CUSTOM['expected_model']
        else:assert data['runtime']==CUSTOM
    assert not (tmp_path/'run').exists()


def base_module():
    """Load the actual adapter with only optional Harbor types replaced."""
    modules={}
    mapping={'harbor.agents.installed.base':['BaseInstalledAgent','CliFlag','with_prompt_template'],
        'harbor.environments.base':['BaseEnvironment'],'harbor.models.agent.context':['AgentContext'],
        'harbor.models.agent.name':['AgentName'],'harbor.models.trajectories':['Agent','FinalMetrics','Metrics','Observation','ObservationResult','Step','ToolCall','Trajectory']}
    for name,attrs in mapping.items():
        m=ModuleType(name)
        for attr in attrs:setattr(m,attr,type(attr,(),{}))
        modules[name]=m
    modules['harbor.agents.installed.base'].CliFlag=lambda *a,**k:None
    modules['harbor.agents.installed.base'].with_prompt_template=lambda fn:fn
    spec=importlib.util.spec_from_file_location('goskills_eval._runtime_base',ROOT/'evaluation/harbor_base.py')
    m=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,modules):spec.loader.exec_module(m)
    return m


def test_actual_terminal_payload_and_response_gate(tmp_path):
    module=base_module();agent=object.__new__(module.DirectAPIBashAgent)
    agent.model_name=CUSTOM['model'];agent._resolved_flags=resolve_runtime(CUSTOM).agent_kwargs()
    payload=agent._request_payload([{'role':'user','content':'test'}],include_reasoning=True,use_max_completion_tokens=True)
    assert payload['model']==CUSTOM['model'] and payload['max_tokens']==4096
    assert 'reasoning_effort' not in payload and 'max_completion_tokens' not in payload
    agent._resolved_flags=resolve_runtime().agent_kwargs();agent.model_name='gpt-5.4'
    original=agent._request_payload([],include_reasoning=True,use_max_completion_tokens=True)
    assert original['reasoning_effort']=='low' and original['max_completion_tokens']==4096 and original['temperature']==0
    agent._resolved_flags=resolve_runtime(CUSTOM).agent_kwargs()|{'request_audit_root':str(tmp_path/'audit')}
    agent.model_name=CUSTOM['model'];agent.logs_dir=tmp_path/'trial/agent';agent._api_calls=[];agent._request_attempt_uuid='synthetic'
    async def reply(*a,**k):return {'model':CUSTOM['expected_model']}
    with patch.object(module,'chat_completion',reply):assert asyncio.run(agent._chat_completion([]))['model']==CUSTOM['expected_model']
    async def wrong(*a,**k):return {'model':'wrong'}
    with patch.object(module,'chat_completion',wrong):
        with pytest.raises(ValueError,match='actual_model'):asyncio.run(agent._chat_completion([]))


def test_alfworld_real_chat_uses_profile_and_rejects_wrong_model(tmp_path):
    from goskills_eval.alfworld import chat as module
    sent=[];actual=[CUSTOM['expected_model']];usage=NS(prompt_tokens=12,completion_tokens=3)
    def create(**kwargs):
        sent.append(kwargs)
        return NS(model=actual[0],usage=usage,choices=[NS(message=NS(content='done'))],model_dump=lambda:{'model':actual[0]})
    fake=ModuleType('openai');fake.OpenAI=lambda **k:NS(chat=NS(completions=NS(create=create)))
    with patch.dict(sys.modules,{'openai':fake}),patch.object(module,'credentials',return_value=('synthetic','https://invalid.local')):
        chat=module.Chat(tmp_path,NS(_record_usage=lambda *a,**k:None),runtime=CUSTOM)
        assert chat([],CUSTOM['model'])=='done'
        assert sent[0]['max_tokens']==4096 and 'reasoning_effort' not in sent[0]
        actual[0]='wrong'
        with pytest.raises(RuntimeError,match='chat_request_failed'):chat([],CUSTOM['model'])
        assert len(sent)==2 and chat.failed
        assert len(chat.calls)==1


def test_request_accounting_records_actual_payload_fields(tmp_path):
    import httpx
    from goskills_eval import async_http
    client=httpx.AsyncClient;sent=[];calls=[]
    def handler(request):
        sent.append(json.loads(request.content));return httpx.Response(200,json={'model':CUSTOM['expected_model'],'usage':{'prompt_tokens':12,'completion_tokens':3}})
    def make(**kwargs):return client(transport=httpx.MockTransport(handler),**kwargs)
    with patch.object(async_http.httpx,'AsyncClient',make):
        asyncio.run(async_http.chat_completion([],endpoint='https://test.invalid/chat/completions',model=CUSTOM['model'],payload_factory=lambda *a,**k:{'model':CUSTOM['model'],'messages':[],'max_tokens':4096},headers_factory=lambda:{},calls=calls,logs_dir=tmp_path,redact=lambda x:x,utc_now=lambda:'synthetic'))
    assert len(sent)==1 and calls[0]['max_token_field']=='max_tokens' and not calls[0]['include_reasoning']


def test_tb2_actual_transport_uses_custom_model_gate_without_retry(tmp_path):
    import goskills_eval
    base=base_module()
    spec=importlib.util.spec_from_file_location('goskills_eval._runtime_tb2',ROOT/'evaluation/terminal_agent.py')
    module=importlib.util.module_from_spec(spec)
    with patch.object(goskills_eval,'harbor_base',base,create=True),patch.dict(sys.modules,{'goskills_eval.harbor_base':base}):spec.loader.exec_module(module)
    agent=object.__new__(module.TB2Agent)
    agent.model_name=CUSTOM['model'];agent._resolved_flags=resolve_runtime(CUSTOM).agent_kwargs()|{'method':'noskills'}
    agent.logs_dir=tmp_path;agent.transport=[];agent._api_calls=[];agent._turn_count=1;agent.transport_fatal=False
    actual=[CUSTOM['expected_model']];bodies=[]
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,content,headers):
            bodies.append(json.loads(content))
            return NS(status_code=200,json=lambda:{'model':actual[0],'usage':{'prompt_tokens':10,'completion_tokens':2},'choices':[{'message':{'content':'done'}}]})
    with patch.object(module.httpx,'AsyncClient',Client),patch.object(module,'credentials',return_value=('synthetic','https://test.invalid')):
        assert asyncio.run(agent._chat_completion([]))['model']==CUSTOM['expected_model']
        assert bodies[0]['max_tokens']==4096 and 'reasoning_effort' not in bodies[0]
        actual[0]='wrong'
        with pytest.raises(RuntimeError,match='model_gate'):asyncio.run(agent._chat_completion([]))
    assert len(bodies)==2 and len(agent._api_calls)==1 and agent.transport_fatal


def test_campaign_rejects_valid_receipt_from_different_runtime(tmp_path):
    from test_campaign import CampaignTests
    from goskills_eval.experiments.run import build_plan,execute_plan
    config=CampaignTests().fixture(tmp_path)
    plan=build_plan(config,'tb2',['noskills'],tmp_path/'run')
    def fake(command,**kwargs):
        dest=Path(command[command.index('--output')+1]);dest.mkdir(parents=True)
        (dest/'receipt.json').write_text(json.dumps({'status':'VALID','method':'noskills','runtime':CUSTOM,'reward':1}))
        return NS(returncode=0)
    with pytest.raises(RuntimeError,match='VALID receipt'):execute_plan(plan,run_command=fake)
    state=json.loads((tmp_path/'run/STATUS.json').read_text())
    assert state['status']=='BLOCKED' and state['rows'][0]['status']=='PROCESS_FAILED'
