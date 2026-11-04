"""Output and credential-boundary helpers; no deployment-specific paths."""
from pathlib import Path
import datetime,hashlib,json,os

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def load(path):return json.loads(Path(path).read_text())
def write(path,value,exclusive=False):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 target=path if exclusive else path.with_suffix(path.suffix+'.tmp')
 with target.open('x' if exclusive else 'w') as f:
  json.dump(value,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')
 if not exclusive:os.replace(target,path)
def credentials():
 key=os.environ.get('OPENAI_API_KEY')
 if not key:raise RuntimeError('Set OPENAI_API_KEY in your local environment')
 return key,(os.environ.get('OPENAI_BASE_URL') or 'https://api.openai.com/v1')
