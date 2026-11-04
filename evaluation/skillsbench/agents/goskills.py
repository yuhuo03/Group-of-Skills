"""Five SkillsBench conditions over the original method-neutral bash agent.

Retrieval commands are dispatched to an owned host helper. Ordinary bash remains
inside the task container. This transport port does not inject API credentials,
upstream Python installations or an alternate TB2 system prompt into the task.
"""
from pathlib import Path
import asyncio,base64,json,os,sys
from goskills_eval.harbor_base import DirectAPIBashAgent,CliFlag,redact_secret
from goskills_eval.skillsbench.task_pack import METHODS
from goskills_eval.skillsbench.bridge import parse_query_command
from goskills_eval.utils import write

class SkillsBenchAgent(DirectAPIBashAgent):
 CLI_FLAGS=DirectAPIBashAgent.CLI_FLAGS+[
  CliFlag('method',cli='',type='str',default='noskills'),
  CliFlag('method_resources',cli='',type='str',default='{}'),
  CliFlag('guide_path',cli='',type='str',default=''),
  CliFlag('retrieval_python',cli='',type='str',default='')]
 @property
 def method(self):return self._resolved_flags['method']
 async def install(self,environment):
  if self.method not in METHODS:raise ValueError('Unknown method')
  await super().install(environment)
  guide=Path(self._resolved_flags['guide_path']).read_bytes()
  encoded=base64.b64encode(guide).decode('ascii')
  command="python3 - <<'PY'\nimport base64\nfrom pathlib import Path\nPath('/root/AGENTS.md').write_bytes(base64.b64decode("+repr(encoded)+"))\nPY"
  result=await self.exec_as_root(environment,command=command)
  if result is not None and getattr(result,'return_code',0)!=0:raise RuntimeError('method_guidance_install_failed')
  self._retrieval_count=0
  self._successful_retrievals=0
 async def _run_bash(self,environment,command):
  try:query=parse_query_command(command,self.method)
  except ValueError as exc:return 'Retrieval command rejected: '+str(exc)
  if query is None:return await super()._run_bash(environment,command)
  self._retrieval_count=getattr(self,'_retrieval_count',0)+1
  directory=Path(self.logs_dir)/'retrievals'/f'{self._retrieval_count:04d}'
  resources=json.loads(self._resolved_flags['method_resources'])
  payload={'method':self.method,'query':query,'directory':str(directory),'resources':resources}
  env=dict(os.environ)
  interpreter=self._resolved_flags.get('retrieval_python') or sys.executable
  if self.method in {'vector','native-gos'} and not self._resolved_flags.get('retrieval_python'):raise RuntimeError('retrieval_python_required')
  process=await asyncio.create_subprocess_exec(interpreter,'-B','-m','goskills_eval.skillsbench.query',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env)
  try:
   out,err=await asyncio.wait_for(process.communicate(json.dumps(payload).encode()),timeout=180)
  except BaseException:
   if process.returncode is None:process.terminate()
   try:await asyncio.wait_for(process.wait(),timeout=5)
   except asyncio.TimeoutError:
    if process.returncode is None:process.kill()
    await process.wait()
   raise
  try:result=json.loads(out)
  except (ValueError,UnicodeDecodeError):raise RuntimeError('retrieval_protocol_failed') from None
  if process.returncode or result.get('status')!='PASSED':raise RuntimeError('method_retrieval_failed')
  self._successful_retrievals=getattr(self,'_successful_retrievals',0)+1
  write(Path(self.logs_dir)/'retrieval_transport.json',{'method':self.method,'successful_calls':self._retrieval_count,'transport':'host-standalone-query-v1'})
  return redact_secret('$ '+command+'\nexit_code=0\n'+result['content'])

 async def run(self,instruction,environment,context):
  failed=False
  try:
   await super().run(instruction,environment,context)
  except asyncio.CancelledError:
   self._finish_status='agent_timeout'
   raise
  except BaseException:
   failed=True
   raise
  finally:
   write(Path(self.logs_dir)/'agent_receipt.json',{
    'method':self.method,'finish_status':getattr(self,'_finish_status','failed' if failed else 'unknown'),
    'actual_models':sorted({c['response'].get('model','unknown') for c in self._api_calls}),
    'api_calls':len(self._api_calls),'transport_fatal':failed,
    'retrieval_count':getattr(self,'_retrieval_count',0),
    'successful_retrievals':getattr(self,'_successful_retrievals',0),
    'token_usage':{'input':self._input_tokens,'output':self._output_tokens,'cached':self._cache_tokens}})
