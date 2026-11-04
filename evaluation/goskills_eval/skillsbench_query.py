"""One owned retrieval subprocess; stdin/stdout JSON, no shell execution."""
import contextlib,json,sys
from pathlib import Path
from .common import write

def main():
 payload=json.load(sys.stdin);directory=Path(payload['directory'])
 try:
  from .method_backend import query
  resources=payload['resources']
  directory.mkdir(parents=True,exist_ok=True)
  # Upstream libraries may print diagnostics; reserve stdout for the JSON protocol.
  with (directory/'backend-private.log').open('x') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
   content=query(payload['method'],payload['query'],directory,
     skills_root=resources['skills_root'],pool=resources.get('pool'),
     workspace=resources.get('workspace'),upstream=resources.get('upstream'),
     source_root='/opt/graphskills/skills')
  write(directory/'receipt.json',{'status':'PASSED','method':payload['method'],'transport':'host-standalone-query-v1'},True)
  result={'status':'PASSED','content':content}
 except Exception as exc:result={'status':'FAILED','error_type':type(exc).__name__}
 print(json.dumps(result));return 0 if result['status']=='PASSED' else 1
if __name__=='__main__':raise SystemExit(main())
