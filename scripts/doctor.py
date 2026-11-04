#!/usr/bin/env python3
"""Read-only local setup checks. No provider request or Docker command is made."""
from pathlib import Path
import argparse, hashlib, importlib.metadata, json, os, re, shutil, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
COMMIT='203f60a2c689da055ce1ac351eb3cb9912a3bca7'
RETRIEVAL_PACKAGES={'graph-skills':'0.1.0','alfworld':'0.4.2','textworld':'1.7.0'}
RUNTIME_PROBE="""import importlib.metadata,json,sys
packages={}
for name in ('graph-skills','alfworld','textworld','openai'):
 try: packages[name]=importlib.metadata.version(name)
 except importlib.metadata.PackageNotFoundError: packages[name]=None
print(json.dumps({'python':list(sys.version_info[:3]),'packages':packages}))
"""

def retrieval_interpreter(value, base):
 """Keep the venv bin/python symlink: resolving it would select system Python."""
 if not isinstance(value,str) or not value.strip():
  raise ValueError('Configure retrieval_python as a Python executable path')
 candidate=Path(value).expanduser()
 if not candidate.is_absolute():candidate=Path(base)/candidate
 candidate=Path(os.path.abspath(candidate))
 if not candidate.is_file() or not os.access(candidate,os.X_OK):
  raise ValueError('retrieval_python must be an existing executable file')
 return candidate

def probe_retrieval_runtime(executable):
 """Only stdlib metadata imports; no evaluator, provider, simulator or shell."""
 try:
  result=subprocess.run([str(executable),'-I','-B','-c',RUNTIME_PROBE],capture_output=True,text=True,timeout=15)
 except subprocess.TimeoutExpired:
  raise ValueError('Retrieval runtime metadata check timed out') from None
 except (OSError,UnicodeError):
  raise ValueError('Retrieval Python executable could not start') from None
 if result.returncode!=0:
  raise ValueError('Retrieval runtime metadata check failed')
 try:
  if len(result.stdout)>16384:raise ValueError()
  data=json.loads(result.stdout)
  versions=data['packages'];py=data['python']
  if set(data)!={'python','packages'} or set(versions)!=set(RETRIEVAL_PACKAGES)|{'openai'}:raise ValueError()
  if not isinstance(py,list) or len(py)!=3 or any(type(v) is not int or v<0 for v in py):raise ValueError()
  if any(v is not None and (not isinstance(v,str) or not re.fullmatch(r'[0-9A-Za-z.+_-]{1,64}',v)) for v in versions.values()):raise ValueError()
 except (ValueError,KeyError,TypeError):
  raise ValueError('Retrieval runtime returned invalid metadata') from None
 return data

def runtime_checks(cfg, base, record):
 record('python_for_harbor',sys.version_info[:2]>=(3,12),'Harbor runtime requires Python >=3.12')
 for name,expected in [('harbor','0.20.0'),('httpx','0.28.1')]:
  try:actual=importlib.metadata.version(name)
  except importlib.metadata.PackageNotFoundError:actual=None
  record('package_'+name,actual==expected,actual)
 try:
  executable=retrieval_interpreter(cfg.get('retrieval_python'),base)
  record('retrieval_python_executable',True,str(executable))
  probe=probe_retrieval_runtime(executable)
 except ValueError as exc:
  record('retrieval_runtime',False,str(exc))
 else:
  record('retrieval_runtime',True,'Local metadata check only; no provider imports')
  record('python_for_retrieval',probe['python'][:2]==[3,12],'.'.join(map(str,probe['python'])))
  for name,expected in RETRIEVAL_PACKAGES.items():
   actual=probe['packages'][name]
   record('retrieval_package_'+name,actual==expected,actual)
  actual=probe['packages']['openai']
  record('retrieval_package_openai',isinstance(actual,str) and re.match(r'^1\.',actual) is not None,actual)
 record('docker_command_available',shutil.which('docker') is not None,'Daemon not contacted')
 record('chat_credential_configured',bool(os.environ.get('OPENAI_API_KEY')))
 record('embedding_credential_configured',bool(os.environ.get('OPENAI_API_KEY')))

def check(config, runtime=False):
 p=Path(config).resolve();cfg=json.loads(p.read_text());base=p.parent;checks=[]
 def record(name,ok,detail=None):checks.append({'check':name,'ok':bool(ok),'detail':detail})
 def path(v):
  q=Path(v).expanduser();return (base/q).resolve() if not q.is_absolute() else q
 for k in ['upstream','skills_root','workspace','pool']:
  q=path(cfg.get(k,''));record(k,q.exists() and bool(cfg.get(k)),str(q))
 upstream=path(cfg.get('upstream',''))
 if (upstream/'.git').exists():
  z=subprocess.run(['git','-C',str(upstream),'rev-parse','HEAD'],capture_output=True,text=True)
  clean=subprocess.run(['git','-C',str(upstream),'diff','--quiet','HEAD','--'],capture_output=True)
  record('upstream_commit',z.returncode==0 and z.stdout.strip()==COMMIT and clean.returncode==0,z.stdout.strip())
 else:record('upstream_commit',False,'Pinned GoS git checkout required')
 skills=path(cfg.get('skills_root',''));count=sum(1 for _ in skills.rglob('SKILL.md')) if skills.is_dir() else 0
 record('nonempty_skill_library',count>0,{'skill_documents':count,'historical_count':2000})
 workspace=path(cfg.get('workspace',''))
 for n in ['graph_igraph_data.pklz','construction_report.json']:
  record('workspace_'+n,(workspace/n).is_file())
 record('embedding_1536_index',len(list(workspace.glob('entities_hnsw_index_1536.bin')))==1)
 members=json.loads((ROOT/'evaluation/experiments/configs/task_ids.json').read_text())
 for b in ['skillsbench','tb2']:
  s=cfg.get(b,{})
  if not s:record(b,False,'Missing benchmark section');continue
  r=path(s.get('tasks_root',''));tasks=s.get('tasks',members[b]);missing=[n for n in tasks if not (r/n/'task.toml').is_file()]
  record(b+'_tasks',not missing,{'selected':len(tasks),'missing':missing})
 a=cfg.get('alfworld',{});record('alfworld_config',bool(a.get('config')) and path(a.get('config','')).is_file())
 mf=path(a.get('games_manifest',''))
 if mf.is_file():
  games=json.loads(mf.read_text());tasks=a.get('tasks',members['alfworld']);root=path(a.get('data_root',''));missing=[]
  for t in tasks:
   v=games.get(t);expected=v.get('sha256') if isinstance(v,dict) else None;v=v.get('path') if isinstance(v,dict) else v
   game=(root/v).resolve() if v else None
   if not game or not game.is_relative_to(root.resolve()) or not game.is_file() or (expected and hashlib.sha256(game.read_bytes()).hexdigest()!=expected):missing.append(t)
  record('alfworld_games',not missing,{'selected':len(tasks),'missing':missing})
 else:record('alfworld_games',False,'Missing games manifest')
 if runtime:
  runtime_checks(cfg,base,record)
 return {'status':'PASSED' if all(c['ok'] for c in checks) else 'SETUP_INCOMPLETE','checks':checks,'api_requests':0,'docker_commands':0}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--runtime',action='store_true');a=p.parse_args();r=check(a.config,a.runtime);print(json.dumps(r,indent=2));return r['status']!='PASSED'
if __name__=='__main__':sys.exit(main())
