"""Lossless read-only SQLite maps under original task memory budgets."""
from pathlib import Path
from collections.abc import Mapping
from functools import lru_cache
import hashlib,json,sqlite3,argparse,importlib.util,sys,re
from contextlib import closing

MAPS=('skills','groups','facet_index','member_index')
FILES={'maps.sqlite','adjacency.sqlite','header.json'}

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
 return h.hexdigest()
class DiskMap(Mapping):
 __hash__=object.__hash__
 def __init__(self,path,kind):
  self.db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro&immutable=1',uri=True);self.kind=kind
 @lru_cache(maxsize=64)
 def __getitem__(self,key):
  row=self.db.execute('SELECT value FROM maps WHERE kind=? AND key=?',(self.kind,key)).fetchone()
  if row is None:raise KeyError(key)
  return json.loads(row[0])
 def __iter__(self):return (row[0] for row in self.db.execute('SELECT key FROM maps WHERE kind=? ORDER BY key',(self.kind,)))
 def __len__(self):return self.db.execute('SELECT count(*) FROM maps WHERE kind=?',(self.kind,)).fetchone()[0]
class Adjacency(Mapping):
 def __init__(self,path):self.db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
 def __getitem__(self,key):
  row=self.db.execute('SELECT value FROM adjacency WHERE key=?',(key,)).fetchone()
  if row is None:raise KeyError(key)
  return json.loads(row[0])
 def __iter__(self):return (row[0] for row in self.db.execute('SELECT key FROM adjacency ORDER BY key'))
 def __len__(self):return self.db.execute('SELECT count(*) FROM adjacency').fetchone()[0]
class FrozenPool(dict):
 def __deepcopy__(self,memo):return self

def compile_pool(source,output):
 """Losslessly compile a validated JSON pool into a new, read-only cache.

 Receipt publication is last. An interrupted output has no valid receipt and
 is never accepted by the reader; it is not overwritten on a later invocation.
 """
 from goskills import retrieval
 from goskills.config import canonical_hash
 from goskills.io import read_json,validate_pool
 from goskills_eval.skill import validate_output
 source=Path(source).resolve();output=Path(output).resolve()
 validate_output(output,pool=source)
 if output.exists():raise FileExistsError('Compiled output must be a new directory')
 before=digest(source);pool=validate_pool(read_json(source))
 core={p.name:digest(p) for p in Path(retrieval.__file__).parent.glob('*.py')}
 for kind in (*MAPS,'adjacency'):
  if not isinstance(pool.get(kind),dict) or any(not isinstance(k,str) for k in pool[kind]):
   raise ValueError('Compiled pool requires string-keyed maps: '+kind)
 header={k:v for k,v in pool.items() if k not in (*MAPS,'adjacency')}
 encode=lambda v:json.dumps(v,ensure_ascii=False,allow_nan=False,separators=(',',':'))
 output.mkdir(parents=True,exist_ok=False)
 with closing(sqlite3.connect(output/'maps.sqlite')) as db:
  with db:
   db.execute('CREATE TABLE maps (kind TEXT, key TEXT, value TEXT, PRIMARY KEY (kind,key))')
   for kind in MAPS:
    db.executemany('INSERT INTO maps VALUES (?,?,?)',((kind,k,encode(v)) for k,v in sorted(pool[kind].items())))
  for kind in MAPS:
   actual={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM maps WHERE kind=?',(kind,))}
   if actual!=pool[kind]:raise ValueError('Compiled map did not preserve every record: '+kind)
 with closing(sqlite3.connect(output/'adjacency.sqlite')) as db:
  with db:
   db.execute('CREATE TABLE adjacency (key TEXT PRIMARY KEY, value TEXT)')
   db.executemany('INSERT INTO adjacency VALUES (?,?)',((k,encode(v)) for k,v in sorted(pool['adjacency'].items())))
  if {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM adjacency')}!=pool['adjacency']:
   raise ValueError('Compiled adjacency did not preserve every record')
 with (output/'header.json').open('x',encoding='utf-8') as handle:handle.write(encode(header)+'\n')
 if json.loads((output/'header.json').read_text())!=header:raise ValueError('Compiled header mismatch')
 if digest(source)!=before or any(digest(Path(retrieval.__file__).parent/n)!=h for n,h in core.items()):
  raise ValueError('Source pool or retrieval policy changed during compilation')
 receipt={'status':'COMPILED_EXACT','original_pool_hash':canonical_hash(pool),
          'source_pool_sha256':before,'files':{n:digest(output/n) for n in sorted(FILES)},
          'core_sources':core,'records':{k:len(pool[k]) for k in (*MAPS,'adjacency')}}
 with (output/'RECEIPT.json').open('x',encoding='utf-8') as handle:handle.write(encode(receipt)+'\n')
 return receipt


def checked_receipt(directory):
 from goskills import retrieval
 directory=Path(directory)
 receipt=json.loads((directory/'RECEIPT.json').read_text())
 if receipt.get('status')!='COMPILED_EXACT' or not re.fullmatch('[0-9a-f]{64}',receipt.get('original_pool_hash','')):
  raise ValueError('Invalid compiled pool receipt')
 if set(receipt.get('files',{}))!=FILES:
  raise ValueError('Compiled receipt must cover exactly the three cache files')
 core={p.name for p in Path(retrieval.__file__).parent.glob('*.py')}
 if set(receipt.get('core_sources',{}))!=core:
  raise ValueError('Compiled receipt must cover the complete retrieval source')
 for root,records in [(directory,receipt['files']),(Path(retrieval.__file__).parent,receipt['core_sources'])]:
  for name,h in records.items():
   if (root/name).is_symlink() or digest(root/name)!=h:
    raise ValueError('Compiled pool or retrieval source hash mismatch: '+name)
 return receipt

def retriever(directory,source_root):
 from goskills import retrieval
 directory=Path(directory);receipt=checked_receipt(directory)
 pool=FrozenPool(json.loads((directory/'header.json').read_text()));pool['adjacency']=Adjacency(directory/'adjacency.sqlite')
 for kind in ['skills','groups','facet_index','member_index']:pool[kind]=DiskMap(directory/'maps.sqlite',kind)
 # Load the same verified policy bytes into a per-instance module. Its globals
 # can recognize this disk map without patching the shared JSON retriever or
 # retaining previous caches through a chain of global hash wrappers.
 spec=importlib.util.spec_from_file_location('goskills._compiled_retrieval',retrieval.__file__)
 policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
 original_validate=policy.validate_pool;original_hash=policy.canonical_hash
 policy.validate_pool=lambda value: value if value is pool else original_validate(value)
 policy.canonical_hash=lambda value: receipt['original_pool_hash'] if value is pool else original_hash(value)
 return policy.Retriever(pool,source_root=source_root)

def main(argv=None):
 argv=sys.argv[1:] if argv is None else list(argv)
 if argv and argv[0]=='compile':
  p=argparse.ArgumentParser(description='Compile a JSON group pool locally; no API calls')
  p.add_argument('--pool',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
  a=p.parse_args(argv[1:]);receipt=compile_pool(a.pool,a.output)
  print(json.dumps({'status':receipt['status'],'output':str(a.output),'records':receipt['records']}));return
 p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--query',required=True);p.add_argument('--source-root',required=True);p.add_argument('--json',action='store_true');a=p.parse_args(argv);result=retriever(a.cache,a.source_root).query(a.query)
 from goskills.validation import validate_bundle
 validate_bundle(result);print(json.dumps(result,ensure_ascii=False) if a.json else result['rendered_context'])
if __name__=='__main__':main()
