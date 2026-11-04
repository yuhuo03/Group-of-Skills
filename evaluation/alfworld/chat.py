from goskills_eval.utils import *
import time,random
from goskills_eval.runtime import resolve_runtime, ALFWORLD_SETTINGS

class Chat:
 def __init__(self,directory,upstream,runtime=None):
  self.runtime=resolve_runtime(runtime)
  from openai import OpenAI
  self.client=OpenAI(api_key=credentials()[0],base_url=credentials()[1],max_retries=0,timeout=90)
  self.directory=directory;self.upstream=upstream;self.calls=[];self.events=[];self.failed=False
 def __call__(self,messages,model):
  if model!=self.runtime.model:raise ValueError('requested_model_mismatch')
  reply=None
  parameters={self.runtime.completion_token_field:ALFWORLD_SETTINGS['max_completion_tokens']}
  if self.runtime.reasoning_effort is not None:parameters['reasoning_effort']=self.runtime.reasoning_effort
  for attempt in range(1,6):
   event={'at':now(),'turn':len(self.calls)+1,'request_attempt':attempt,'request_model':model,'input_sha256':hashlib.sha256(json.dumps(messages,ensure_ascii=False).encode()).hexdigest()}
   try:
    reply=self.client.chat.completions.create(model=model,messages=messages,timeout=90,**parameters)
    self.runtime.validate_response(reply.model)
    assert reply.usage is not None and reply.usage.prompt_tokens>0 and reply.usage.completion_tokens>=0,'usage_missing'
    assert reply.choices and reply.choices[0].message.content is not None,'completion_missing'
    event.update(status='success',actual_model=reply.model);self.events.append(event);write(self.directory/'transport.json',self.events)
    d=reply.model_dump();self.calls.append(d);write(self.directory/'api_calls.json',self.calls)
    self.upstream._record_usage(reply.usage,bucket='agent')
    return reply.choices[0].message.content
   except Exception as exc:
    status=getattr(exc,'status_code',None);event.update(status='error',error_type=type(exc).__name__,http_status=status);self.events.append(event);write(self.directory/'transport.json',self.events)
    retryable=status in {408,429,500,502,503,504,524} or type(exc).__name__ in {'APITimeoutError','APIConnectionError'}
    if not retryable or attempt==5:self.failed=True;raise RuntimeError('chat_request_failed:'+type(exc).__name__) from None
    time.sleep(5*2**(attempt-1)+random.uniform(1,3))
  raise AssertionError('unreachable')

