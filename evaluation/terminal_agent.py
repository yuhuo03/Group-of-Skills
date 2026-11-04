"""Portable TB2 Harbor adapter, preserving GPT-5.4 prompt/budget/transport semantics.

Five methods use the same terminal prompt and task budget. Baseline retrieval
is delegated to the compatible official GoS implementation in isolated helpers.
"""
from goskills_eval.utils import *
from goskills_eval import harbor_base as base
import sys,asyncio,json,hashlib,time,uuid,contextlib,httpx,shlex
from goskills_eval.runtime import pinned_config
from goskills_eval.runtime import METHODS
def skill_env(offline=False):return dict(os.environ)
def proc(pid):
 try:
  fields=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()
  return {'pid':pid,'state':fields[0],'pgid':int(fields[2]),'start_ticks':int(fields[19])}
 except FileNotFoundError:return None

class TB2Agent(base.DirectAPIBashAgent):
 CLI_FLAGS=base.DirectAPIBashAgent.CLI_FLAGS+[base.CliFlag('method',cli='',type='str',default='noskills'),base.CliFlag('task_budget_sec',cli='',type='int',default=600)]+[base.CliFlag(name,cli='',type='str',default='') for name in ('skills_root','pool','workspace','upstream','retrieval_python')]
 @staticmethod
 def name():return 'tb2-five-direct-api'
 def version(self):return 'tb2-five-v2'
 @property
 def method(self):return self._resolved_flags['method']
 async def install(self,environment):
  result=await environment.exec(command='command -v bash >/dev/null && command -v timeout >/dev/null',timeout_sec=20)
  assert result.return_code==0,'bash_missing'
 def _tools(self):
  t=super()._tools();t[0]['function']['description']='Run a bash command inside the Terminal-Bench task container.'
  if self.method in {'vector','native-gos','goskills-d'}:
   t.append({'type':'function','function':{'name':'retrieve_skills','description':'Retrieve skills for a focused visible goal or blocker; use relevant source files only when useful.','parameters':{'type':'object','properties':{'query':{'type':'string'}},'required':['query'],'additionalProperties':False}}})
  return t
 async def _run_bash(self,environment,command):
  # Keep the official overall agent deadline, with in-container process-group cleanup.
  remaining=max(0.1,self._command_deadline-time.monotonic()-2.0)
  limit=f'{remaining:.3f}'
  wrapped='timeout -s TERM -k 1 '+limit+' /bin/bash -c '+shlex.quote('set -o pipefail; '+command)
  event={'at':now(),'command_sha256':hashlib.sha256(command.encode()).hexdigest(),'remaining_task_seconds':remaining,'status':'STARTED'}
  self.command_events.append(event);write(Path(self.logs_dir)/'command_events.json',self.command_events)
  try:
   result=await environment.exec(command=wrapped,timeout_sec=None)
   event.update(status='TIME_LIMIT' if result.return_code==124 else 'RETURNED',return_code=result.return_code)
   output=[f'$ {command}',f'exit_code={result.return_code}']
   if result.stdout:output.extend(['stdout:',result.stdout])
   if result.stderr:output.extend(['stderr:',result.stderr])
   if result.return_code==124:output.append('Command reached the remaining task deadline; its process group was terminated.')
   return base.clip(base.redact_secret('\n'.join(output)),self._max_observation_chars)
  except asyncio.CancelledError:
   event.update(status='CANCELLED');raise
  except Exception as e:
   event.update(status='INFRASTRUCTURE_ERROR',error_type=type(e).__name__);raise
  finally:write(Path(self.logs_dir)/'command_events.json',self.command_events)
 async def retrieve(self,query):
  interpreter=self._resolved_flags.get('retrieval_python')
  if self.method in {'vanilla','vector','native-gos'} and not interpreter:
   raise ValueError('Separate official GoS retrieval Python is required')
  interpreter=interpreter or sys.executable
  self.retrieval_count+=1;directory=Path(self.logs_dir)/'retrievals'/f'{self.retrieval_count:04d}'
  payload={'method':self.method,'query':query,'directory':str(directory),**{name:self._resolved_flags.get(name) or None for name in ('skills_root','pool','workspace','upstream')}}
  with (Path(self.logs_dir)/f'retrieval-{self.retrieval_count:04d}-private.log').open('xb') as log:
   p=await asyncio.create_subprocess_exec(interpreter,'-B','-m','goskills_eval.query_helper',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=log,env=skill_env(),cwd=Path.cwd())
   self.skill_child={'pid':p.pid,'identity':proc(p.pid)};write(Path(self.logs_dir)/'skill_child.json',self.skill_child)
   try:
    out,_=await asyncio.wait_for(p.communicate(json.dumps(payload).encode()),timeout=180)
   except BaseException:
    # Only the newly created, owned per-query helper is terminated on its task deadline.
    if p.returncode is None:
     p.terminate()
     try:await asyncio.wait_for(p.wait(),timeout=5)
     except asyncio.TimeoutError:
      p.kill();await p.wait()
    raise
  result=json.loads(out);assert p.returncode==0 and result.get('status')=='PASSED','retrieval_failed'
  self.successful_retrievals+=1
  return result['content']
 async def _chat_completion(self,messages):
  payload=self._request_payload(messages,include_reasoning=True,use_max_completion_tokens=True)
  body=json.dumps(payload,ensure_ascii=False).encode();request_id=uuid.uuid4().hex
  for attempt in range(1,6):
   event={'at':now(),'request_id':request_id,'turn':self._turn_count,'attempt':attempt,'payload_sha256':hashlib.sha256(body).hexdigest(),'status':'STARTED'}
   self.transport.append(event);write(Path(self.logs_dir)/'transport.json',self.transport)
   try:
    async with httpx.AsyncClient(timeout=180,follow_redirects=False) as c:
     response=await c.post(credentials()[1].rstrip('/')+'/chat/completions',content=body,headers={'Authorization':'Bearer '+credentials()[0],'Content-Type':'application/json'})
    event['http_status']=response.status_code
    if response.status_code>=300:raise httpx.HTTPStatusError('request_failed',request=response.request,response=response)
    d=base.redact_secret(response.json())
    if d.get('model')!=self._resolved_flags.get('expected_model',pinned_config()['expected_model']):raise ValueError('actual_model_mismatch')
    u=d.get('usage') or {};assert type(u.get('prompt_tokens')) is int and u['prompt_tokens']>0 and type(u.get('completion_tokens')) is int and u['completion_tokens']>=0,'usage_missing'
    assert d.get('choices') and isinstance(d['choices'][0].get('message'),dict),'completion_missing'
    event.update(status='SUCCESS',actual_model=d['model'],usage=u)
    self._api_calls.append({'response':d,'requested_model':self.model_name,'attempt':attempt,'timestamp':now()});write(Path(self.logs_dir)/'api_calls.json',self._api_calls)
    return d
   except asyncio.CancelledError:
    event.update(status='CANCELLED',usage_status='unknown');raise
   except Exception as e:
    status=event.get('http_status');event.update(status='ERROR',error_type=type(e).__name__,error_code=str(e) if isinstance(e,AssertionError) else None)
    retryable=status in {408,429,500,502,503,504,524} or isinstance(e,(httpx.TimeoutException,httpx.NetworkError))
    if not retryable or attempt==5:self.transport_fatal=True;raise RuntimeError('chat_transport_or_model_gate_failed') from None
    await asyncio.sleep(min(8,2**(attempt-1)))
   finally:write(Path(self.logs_dir)/'transport.json',self.transport)
 async def _save_trajectory(self,environment):
  write(Path(self.logs_dir)/'trajectory.json',base.redact_secret({'schema_version':'tb2-host-trace-v1','method':self.method,'model':self.model_name,'steps':[x.model_dump(mode='json') for x in self._steps],'messages':self.messages,'input_tokens':self._input_tokens,'output_tokens':self._output_tokens,'cached_tokens':self._cache_tokens,'agent_turns':self._turn_count,'tool_calls':self._tool_call_count,'finish_status':getattr(self,'_finish_status','unknown')}))
 async def run(self,instruction,environment,context):
  assert self.method in METHODS
  self.logs_dir.mkdir(parents=True,exist_ok=True);self.retrieval_count=0;self.successful_retrievals=0;self.transport=[];self.transport_fatal=False;self.command_events=[];self._command_deadline=time.monotonic()+int(self._resolved_flags['task_budget_sec'])
  system='You are an autonomous coding agent inside a Terminal-Bench task. Use the bash tool to inspect files, edit files, and verify outputs. Do not ask the user for clarification. Preserve required output paths exactly. Finish with a concise final answer only after the artifact is produced or no further useful action is possible.'
  if self.method!='noskills':system+=' Relevant skills are conditional guidance. Original skill directories are available read-only at /opt/graphskills/skills; inspect applicable scripts/references before reimplementing. Use the task requirements as authority and avoid unrelated library exploration.'
  self.messages=[{'role':'system','content':system},{'role':'user','content':instruction}];self._append_user_step(instruction)
  try:
   if self.method!='noskills':
    content=await self.retrieve(instruction);self.messages.append({'role':'user','content':content});self._append_user_step(content)
   for turn in range(self._max_turns):
    self._turn_count+=1;d=await self._chat_completion(self.messages);metrics=self._record_usage(d);message=d['choices'][0]['message'];self.messages.append(message)
    raw=message.get('tool_calls') or [];self._tool_call_count+=len(raw);calls=[];observations=[]
    for call in raw:
     fun=call.get('function') or {};name=fun.get('name');cid=str(call.get('id') or uuid.uuid4().hex)
     try:args=json.loads(fun.get('arguments') or '{}')
     except (ValueError,TypeError):args={}
     if name=='bash' and args.get('command'):obs=await self._run_bash(environment,str(args['command']))
     elif name=='retrieve_skills' and self.method in {'vector','native-gos','goskills-d'} and args.get('query'):obs=await self.retrieve(str(args['query']))
     else:obs='Unsupported or malformed tool request.'
     calls.append(base.ToolCall(tool_call_id=cid,function_name=name or 'unknown',arguments=args));observations.append(base.ObservationResult(source_call_id=cid,content=obs));self.messages.append({'role':'tool','tool_call_id':cid,'content':obs})
    self._append_agent_step(message.get('content') or '',tool_calls=calls or None,observation=base.Observation(results=observations) if observations else None,metrics=metrics)
    await self._save_trajectory(environment)
    if not raw:self._finish_status='completed';break
   else:self._finish_status='max_turns'
  except asyncio.CancelledError:self._finish_status='agent_timeout';raise
  except Exception:self._finish_status='failed';raise
  finally:
   self.populate_context_post_run(context);await self._save_trajectory(environment)
   write(Path(self.logs_dir)/'agent_receipt.json',{'method':self.method,'finish_status':getattr(self,'_finish_status','unknown'),'actual_models':sorted({c['response']['model'] for c in self._api_calls}),'api_calls':len(self._api_calls),'transport_fatal':self.transport_fatal,'retrieval_count':self.retrieval_count,'successful_retrievals':self.successful_retrievals,'token_usage':{'input':self._input_tokens,'output':self._output_tokens,'cached':self._cache_tokens}})
