"""Fresh SkillsBench method packs, with unchanged task/test/resource inputs.

The method-only oracle removal follows the original baseline convention. The
release performs retrieval on the host instead of installing API routes inside
benchmark containers; no historical image/cache controller is replayed.
"""
from __future__ import annotations
import hashlib,json,os,re,shutil
try:
 import tomllib
except ImportError:
 import tomli as tomllib
from pathlib import Path

METHODS=('noskills','vanilla','vector','native-gos','goskills-d')
COMMANDS={'vector':'vectorskills-query','native-gos':'graphskills-query','goskills-d':'goskills-query'}
COMMON='# Task Environment\n\nBefore implementation, inspect visible task requirements/tests and preserve required output paths. Prefer the shortest verifier-aligned solution and local files.\n'
PROMPT='Before writing or editing solution code, read /root/AGENTS.md if it exists. Follow its skill-access condition, inspect visible requirements/tests, preserve exact output paths, and prefer the shortest verifier-aligned solution.\n\n{{ instruction }}\n'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def tree(root):
 root=Path(root)
 return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts}
def _within(child,parent):return child==parent or parent in child.parents

def guidance(method,upstream=None):
 if method=='noskills':return COMMON+'\nNo external skill library is supplied. Solve the task with the available tools.\n'
 template={'vanilla':'_allskills_template','vector':'_vectorskills_template','native-gos':'_gos_template','goskills-d':'_gos_template'}[method]
 source=Path(upstream)/'evaluation/skillsbench'/template/'AGENTS.md'
 text=source.read_text()
 if method=='vanilla':return text+'\nThe full library is at `/opt/skillsbench/skills`; read skill files on demand.\n'
 if method=='goskills-d':
  text=text.replace('**Graph of Skills** (GoS) workspace','**GoSkills** group pool').replace('graphskills-query','goskills-query').replace('a prebuilt skill graph','a prebuilt group pool').replace('a ranked bundle of skills','a bounded role-labeled contract and skills')
  start=text.index('You must read the retrieval status from that result.');end=text.index('## Reading the Output',start)
  text=text[:start]+'Read the START and DEBT fields. If no anchor/skills were selected, note the no-hit and continue without claiming skill use. Otherwise use only the presented skills and their stated roles.\n\n'+text[end:]
  text+='\nGoSkills uses the fixed START, SUPPORT, CHECK, AVOID, SKILLS, and DEBT fields. Respect the returned roles and report remaining coverage debt. Only the presented skills are selected; unpresented group members are not implied.\n'
 # Historical vector instructions embedded endpoint/env assignments. The release
 # keeps provider configuration on the host and gives an equivalent standalone query.
 if method=='vector':
  text=re.sub(r'```bash\n.*?vectorskills-query ([^\n]+)\n```',r'```bash\nvectorskills-query \1\n```',text,count=1,flags=re.S)
 text=text.replace('This command is available on PATH.', 'This command is handled by the host retrieval bridge when called through the bash tool.')
 text+='\n## Portable retrieval transport\n\nRun '+COMMANDS[method]+' "<visible goal or blocker>" as a standalone bash-tool command. Do not prefix environment assignments, use pipes, redirects, command substitution, or combine it with another shell command. Provider settings stay on the host. Run ordinary filesystem inspection in separate bash calls.\n'
 return text

def inspect_inputs(task,method,output,skills_root=None,pool=None,workspace=None,upstream=None,retrieval_python=None):
 if method not in METHODS:raise ValueError('Unknown SkillsBench method')
 if method in {'vector','native-gos'} and not retrieval_python:raise ValueError('Vector/GoS require --retrieval-python from the separate GoS environment')
 if retrieval_python:
  # Do not resolve interpreter symlinks: venv/bin/python must retain its venv.
  retrieval_python=os.path.abspath(os.path.expanduser(str(retrieval_python)))
  if not Path(retrieval_python).is_file() or not os.access(retrieval_python,os.X_OK):raise ValueError('Retrieval Python must be an executable file')
 task=Path(task).resolve();output=Path(output).resolve()
 for filename in ['task.toml','instruction.md']:
  if not(task/filename).is_file():raise ValueError('Missing SkillsBench task file: '+filename)
 config=tomllib.loads((task/'task.toml').read_text())
 if config.get('environment',{}).get('os','linux')!='linux':raise ValueError('The SkillsBench bash agent requires a Linux task')
 env=task/'environment';dockerfile=env/'Dockerfile'
 compose_files=[env/name for name in ['docker-compose.yaml','compose.yml','compose.yaml','docker-compose.yml'] if (env/name).is_file()]
 if len(compose_files)>1:raise ValueError('Multiple compose files need an explicit merged task definition')
 compose=compose_files[0] if compose_files else env/'docker-compose.yaml'
 if not dockerfile.is_file():raise ValueError('SkillsBench raw task requires environment/Dockerfile; image-only/custom builds need explicit preparation')
 if compose.exists():
  # Harbor 0.20 appends its mount overlay after the original compose file.
  # Preserve services and networking verbatim; no sidecar rewrite is needed.
  text=compose.read_text()
  if re.search(r'(?m)^\s*(?:include|extends)\s*:',text):raise ValueError('External compose include/extends must be materialized inside the raw task')
  if re.search(r'(?m)^\s*build\s*:\s*(?:/|\.\.)',text) or re.search(r'(?m)^\s*context\s*:\s*(?:/|\.\.)',text):raise ValueError('Compose build context outside the raw task is not portable')
 if output.exists():raise FileExistsError('Output already exists')
 if _within(output,task):raise ValueError('Output must be outside the source task')
 for f in task.rglob('*'):
  if f.is_symlink():raise ValueError('Task symlinks must be materialized before preparation')
 docker=(task/'environment/Dockerfile').read_text()
 if re.search(r'# BEGIN (?:CR NATIVE OVERLAY|GOSKILLS|GRAPH SKILLS)',docker):
  raise ValueError('Use a raw task, not a previously method-prepared task pack')
 # Only unambiguous one-source oracle COPY directives are removable automatically.
 for line in docker.splitlines():
  if re.match(r'\s*(COPY|ADD)\s+',line,re.I) and re.search(r'(?<![\w.-])(?:\./)?skills(?:/|\s|"|$)',line):
   if not re.fullmatch(r'\s*COPY\s+(?:--chown=\S+\s+)?(?:\./)?skills/?\s+\S+\s*',line,re.I):
    raise ValueError('Unreviewed oracle-skills Docker COPY/ADD; use a plain one-source COPY directive')
 resources={}
 for key,value in [('skills_root',skills_root),('pool',pool),('workspace',workspace),('upstream',upstream)]:
  if value:
   path=Path(value).resolve()
   if not path.exists():raise ValueError('Missing '+key)
   if _within(output,path):raise ValueError('Output must be outside '+key)
   resources[key]=str(path)
 if method!='noskills':
  if 'skills_root' not in resources or 'upstream' not in resources:raise ValueError('Skill methods require --skills-root and --upstream')
  if not list(Path(resources['skills_root']).glob('*/SKILL.md')):raise ValueError('Skill library contains no SKILL.md files')
  guidance(method,resources['upstream']) # Check exact template availability now.
 if method=='goskills-d' and 'pool' not in resources:raise ValueError('GoSkills D requires --pool')
 if method in {'vector','native-gos'} and 'workspace' not in resources:raise ValueError('Vector/GoS require --workspace')
 return {'task':str(task),'method':method,'output':str(output),'resources':resources,'retrieval_python':retrieval_python,'source_task_sha256':tree(task),'transport':'host-standalone-query-v1','compose_source':compose.relative_to(task).as_posix() if compose.is_file() else None}

def trial_config(plan):
 out=Path(plan['output']);method=plan['method'];resources=plan['resources']
 root='/opt/skillsbench/skills' if method=='vanilla' else '/opt/graphskills/skills'
 mounts=[] if method=='noskills' else [{'type':'bind','source':resources['skills_root'],'target':root,'read_only':True}]
 return {'task':{'path':str(out/'prepared-task')},'trial_name':'gpt54-sb-'+method+'-'+hashlib.sha256(str(out).encode()).hexdigest()[:10],
 'trials_dir':str(out/'trials'),'agent':{'import_path':'goskills_eval.skillsbench.agents.goskills:SkillsBenchAgent','model_name':'gpt-5.4','override_timeout_sec':900,'override_setup_timeout_sec':180,
 'kwargs':{'method':method,'retrieval_python':plan.get('retrieval_python') or '', 'method_resources':json.dumps(resources,sort_keys=True),'guide_path':str(out/'method-AGENTS.md'),'prompt_template_path':str(out/'prompt.txt'),'reasoning_effort':'low','max_turns':60,'max_completion_tokens':4096,'tool_timeout_sec':180,'max_observation_chars':12000,'request_audit_root':str(out/'transport-audit')}},
 'environment':{'type':'docker','delete':True,'mounts':mounts},'timeout_multiplier':1.0}

def prepare(plan):
 task=Path(plan['task']);out=Path(plan['output'])
 if out.exists():raise FileExistsError('Output already exists')
 if plan['method']!='noskills':
  # Verify local tracked source before creating a pack or starting a paid agent.
  from goskills_eval.skill import prepare_upstream
  prepare_upstream(plan['resources']['upstream'])
 out.mkdir(parents=True,exist_ok=False)
 if tree(task)!=plan['source_task_sha256']:raise ValueError('Task changed since planning')
 dest=out/'prepared-task';shutil.copytree(task,dest,ignore=shutil.ignore_patterns('.git','__pycache__','*.pyc'))
 compose_source=plan.get('compose_source')
 if compose_source and compose_source!='environment/docker-compose.yaml':
  (dest/compose_source).rename(dest/'environment/docker-compose.yaml')
 removed=[];oracle=dest/'environment/skills'
 if oracle.exists():
  removed=sorted(p.relative_to(dest).as_posix() for p in oracle.rglob('*') if p.is_file()) if oracle.is_dir() else [oracle.relative_to(dest).as_posix()]
  if oracle.is_dir():shutil.rmtree(oracle)
  else:oracle.unlink()
 docker=dest/'environment/Dockerfile';text=docker.read_text()
 text=re.sub(r'(?im)^\s*COPY\s+(?:--chown=\S+\s+)?(?:\./)?skills/?\s+\S+\s*\n?', '',text)
 docker.write_text(text)
 (out/'method-AGENTS.md').write_text(guidance(plan['method'],plan['resources'].get('upstream')))
 (out/'prompt.txt').write_text(PROMPT)
 protected=['task.toml','instruction.md']+[p.relative_to(task).as_posix() for p in (task/'tests').rglob('*') if p.is_file()]
 for name in protected:
  if sha(task/name)!=sha(dest/name):raise ValueError('Protected task file modified: '+name)
 manifest={**plan,'prepared_task_sha256':tree(dest),'removed_oracle_files':removed,'protected_files':{n:sha(dest/n) for n in protected},'guide_sha256':sha(out/'method-AGENTS.md'),'prompt_sha256':sha(out/'prompt.txt'),
 'changes':['Remove oracle environment/skills and corresponding plain Docker COPY','Normalize a single alternate compose filename to docker-compose.yaml without changing its bytes','Add host-only standalone query bridge guidance','Read-only method skill-library mount; custom compose bytes and services preserved','Original SkillsBench 900-second agent override; native task resource and verifier settings retained'],
 'provider_calls':0,'docker_runs':0}
 (out/'PREPARATION.json').write_text(json.dumps(manifest,indent=2)+'\n')
 config=trial_config(plan);(out/'trial_config.json').write_text(json.dumps(config,indent=2)+'\n')
 return config
