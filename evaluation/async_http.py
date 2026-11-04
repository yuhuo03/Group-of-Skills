"""Cancellable HTTP transport with stable payloads and bounded retries.

Only successful, fully parsed responses enter the existing api_calls contract.
The separate append-only ledger records incomplete/unknown-cost physical POSTs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import uuid

import anyio
import httpx

VARIANTS=((True,True),(False,True),(False,False))
RETRY_HTTP={408,409,425,429,500,502,503,504}
API_CALL_FIELDS={'response','duration_sec','requested_model','include_reasoning',
                 'max_token_field','attempt','timestamp'}


def _known_usage(data):
    usage=data.get('usage') if isinstance(data,dict) else None
    if not isinstance(usage,dict):return None
    values=(usage.get('prompt_tokens',usage.get('input_tokens')),
            usage.get('completion_tokens',usage.get('output_tokens')))
    if not all(type(value) in (int,float) and math.isfinite(value) and value>=0 for value in values):return None
    numeric=lambda value:type(value) in (int,float) and math.isfinite(value) and value>=0
    result={key:value for key,value in usage.items() if key in
            {'prompt_tokens','input_tokens','completion_tokens','output_tokens','total_tokens'} and numeric(value)}
    details={'cached_tokens','reasoning_tokens','accepted_prediction_tokens','rejected_prediction_tokens','audio_tokens','text_tokens'}
    for key in ('prompt_tokens_details','input_tokens_details','completion_tokens_details','output_tokens_details'):
        if isinstance(usage.get(key),dict):
            result[key]={name:value for name,value in usage[key].items() if name in details and numeric(value)}
    return result


def _append(path,event,redact):
    path.parent.mkdir(parents=True,exist_ok=True)
    line=(json.dumps(redact(event),ensure_ascii=False,allow_nan=False)+'\n').encode()
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    try:
        os.fchmod(descriptor,0o600)
        with os.fdopen(descriptor,'ab',closefd=False) as handle:handle.write(line);handle.flush();os.fsync(descriptor)
    finally:os.close(descriptor)


async def _close_client(client):
    """No orphan cleanup task even when cancellation is repeated."""
    interrupted=False
    task=asyncio.create_task(client.aclose())
    with anyio.CancelScope(shield=True):
        while not task.done():
            try:await asyncio.shield(task)
            except asyncio.CancelledError:interrupted=True
        task.result()
    if interrupted:raise asyncio.CancelledError()


def _archive(logs,audit_root,identity,model,utc_now):
    if audit_root is None:return None
    root=Path(audit_root)
    if not root.is_absolute() or root.resolve().is_relative_to(logs.resolve().parent):
        raise ValueError('Public external audit root must be absolute and outside the trial directory')
    if any(part in {'.config','.env'} or 'credential' in part.lower() for part in (*root.parts,*root.resolve().parts)):
        raise ValueError('Private configuration paths cannot be audit roots')
    value=dict(identity or {})
    required={'job_id','trial_id','attempt_uuid','trial_path_sha256'}
    if set(value)!=required or any(not isinstance(v,str) or not v for v in value.values()):
        raise ValueError('External audit needs explicit job/trial/physical-attempt identity')
    attempt=str(uuid.UUID(value['attempt_uuid']))
    if not re.fullmatch('[0-9a-f]{64}',value['trial_path_sha256']):raise ValueError('Invalid public trial path identity')
    def component(value):return re.sub('[^A-Za-z0-9_.-]','_',value)[:100]+'-'+hashlib.sha256(value.encode()).hexdigest()[:12]
    directory=root/component(value['job_id'])/component(value['trial_id'])/attempt
    directory.mkdir(parents=True,exist_ok=True)
    if directory.resolve().is_relative_to(logs.resolve().parent):raise ValueError('Resolved audit path enters trial directory')
    identity_path=directory/'identity.json';binding={'schema_version':1,**value,'requested_model':model}
    try:
        with os.fdopen(os.open(identity_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w',encoding='utf-8') as handle:
            json.dump(binding,handle,indent=2);handle.write('\n');handle.flush();os.fsync(handle.fileno())
    except FileExistsError:
        if json.loads(identity_path.read_text())!=binding:raise ValueError('Refusing reused audit attempt with different identity')
    return directory


async def _post(client,endpoint,body,headers):
    # urllib permits POST301/302/303 -> GET, but refuses POST307/308.
    # Disable implicit replay so every physical POST has its own ledger event.
    response=await client.post(endpoint,content=body,headers=headers,follow_redirects=False)
    visited={}
    for _ in range(10):
        status=response.status_code;location=response.headers.get('location')
        if not location or status not in {301,302,303,307,308}:break
        if response.request.method=='POST' and status in {307,308}:break
        try:target=response.url.join(location)
        except (ValueError,httpx.InvalidURL):break
        key=str(target);visited[key]=visited.get(key,0)+1
        if visited[key]>4 or target.scheme not in {'http','https'}:break
        redirected={key:value for key,value in headers.items() if key.lower() not in {'content-type','content-length'}}
        if (target.scheme,target.host,target.port)!=(response.url.scheme,response.url.host,response.url.port):
            redirected={key:value for key,value in redirected.items() if key.lower()!='authorization'}
        response=await client.get(target,headers=redirected,follow_redirects=False)
    return response


async def chat_completion(messages,*,endpoint,model,payload_factory,headers_factory,
                          calls,logs_dir,redact,utc_now,timeout_sec=180.0,sleep=asyncio.sleep,
                          audit_root=None,trial_identity=None):
    """Same three variants/three attempts as v6; cancellation is never retried.

    httpx's connect/read/write/pool timeout is explicit180s, matching the old
    socket-I/O bound rather than inventing a new whole-completion budget. The
    Harbor agent's existing outer900s deadline can now interrupt this await.
    Test injection of timeout/sleep does not add a production CLI/config option.
    """
    logs=Path(logs_dir);ledger=logs/'request_lifecycle.jsonl'
    archive=_archive(logs,audit_root,trial_identity,model,utc_now)
    completion_id=str(uuid.uuid4());last_error='unknown transport error';completed_usage=None;cancel_logged=False
    client=httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec),follow_redirects=False,
                             trust_env=True)
    def event(kind,*,request_id=None,variant=None,attempt=None,started=None,**extra):
        value={'schema_version':1,'event':kind,'completion_id':completion_id,
               'request_id':request_id,'variant':variant,'attempt':attempt,'timestamp':utc_now(),
               'requested_model':model,'duration_sec':None if started is None else time.monotonic()-started,
               'usage_status':'pending' if kind=='request_start' else 'unknown','usage':None}
        value.update(extra);_append(ledger,value,redact)
        if archive is not None:_append(archive/'request_lifecycle.jsonl',value,redact)
    try:
        for variant,(include_reasoning,use_max_completion_tokens) in enumerate(VARIANTS,1):
            body=json.dumps(payload_factory(messages,include_reasoning=include_reasoning,
                      use_max_completion_tokens=use_max_completion_tokens)).encode('utf-8')
            headers=headers_factory()
            for attempt in range(1,4):
                # Give a pending timeout/cancellation a checkpoint before a new POST.
                await asyncio.sleep(0)
                request_id=str(uuid.uuid4());started=time.monotonic()
                common=dict(request_id=request_id,variant=variant,attempt=attempt,started=started,
                            payload_sha256=hashlib.sha256(body).hexdigest())
                event('request_start',**common)
                try:
                    response=await _post(client,endpoint,body,headers)
                except asyncio.CancelledError:
                    event('request_cancelled',**common,error_type='CancelledError')
                    raise
                except Exception as error:
                    # Exception strings/headers/error response bodies are never logged.
                    last_error=type(error).__name__
                    event('request_end',**common,error_type=last_error,http_status=None)
                else:
                    status=response.status_code
                    if status>=300:
                        last_error='HTTP '+str(status)
                        event('request_end',**common,error_type='HTTPError',http_status=status)
                        if status==400:break  # Exact original compatibility-variant rule.
                        if status not in RETRY_HTTP:raise RuntimeError(last_error) from None
                    else:
                        try:
                            data=redact(json.loads(response.content.decode('utf-8',errors='replace')))
                        except Exception as error:
                            last_error=type(error).__name__
                            event('request_end',**common,error_type=last_error,http_status=status)
                        else:
                            record={'response':data,'duration_sec':time.monotonic()-started,
                                'requested_model':model,'include_reasoning':include_reasoning,
                                'max_token_field':'max_completion_tokens' if use_max_completion_tokens else 'max_tokens',
                                'attempt':attempt,'timestamp':utc_now()}
                            calls.append(record);logs.mkdir(parents=True,exist_ok=True)
                            (logs/'api_calls.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2),encoding='utf-8')
                            if archive is not None:
                                responses=archive/'responses';responses.mkdir(exist_ok=True)
                                with os.fdopen(os.open(responses/(request_id+'.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w',encoding='utf-8') as handle:
                                    json.dump(record,handle,ensure_ascii=False,indent=2);handle.write('\n');handle.flush();os.fsync(handle.fileno())
                            completed_usage=_known_usage(data)
                            event('request_end',**common,error_type=None,http_status=status,
                                  usage_status='known' if completed_usage is not None else 'unknown',usage=completed_usage)
                            return data
                if attempt<3:await sleep(min(8.0,1.0*attempt))
        raise RuntimeError('Direct API request failed: '+last_error) from None
    except asyncio.CancelledError:
        event('completion_cancelled',usage_status='known' if completed_usage is not None else 'unknown',usage=completed_usage)
        cancel_logged=True
        raise
    finally:
        try:await _close_client(client)
        except asyncio.CancelledError:
            if not cancel_logged:
                event('completion_cancelled',usage_status='known' if completed_usage is not None else 'unknown',usage=completed_usage)
            raise
