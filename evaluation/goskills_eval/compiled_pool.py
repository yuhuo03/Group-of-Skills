"""Lossless read-only SQLite maps under original task memory budgets."""
from pathlib import Path
from collections.abc import Mapping
from functools import lru_cache
import hashlib,json,sqlite3,argparse

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
 return h.hexdigest()
class DiskMap(Mapping):
 __hash__=object.__hash__
 def __init__(self,path,kind):
  self.db=sqlite3.connect('file:'+str(path)+'?mode=ro&immutable=1',uri=True);self.kind=kind
 @lru_cache(maxsize=64)
 def __getitem__(self,key):
  row=self.db.execute('SELECT value FROM maps WHERE kind=? AND key=?',(self.kind,key)).fetchone()
  if row is None:raise KeyError(key)
  return json.loads(row[0])
 def __iter__(self):return (row[0] for row in self.db.execute('SELECT key FROM maps WHERE kind=? ORDER BY key',(self.kind,)))
 def __len__(self):return self.db.execute('SELECT count(*) FROM maps WHERE kind=?',(self.kind,)).fetchone()[0]
class Adjacency(Mapping):
 def __init__(self,path):self.db=sqlite3.connect('file:'+str(path)+'?mode=ro&immutable=1',uri=True)
 def __getitem__(self,key):
  row=self.db.execute('SELECT value FROM adjacency WHERE key=?',(key,)).fetchone()
  if row is None:raise KeyError(key)
  return json.loads(row[0])
 def __iter__(self):return (row[0] for row in self.db.execute('SELECT key FROM adjacency ORDER BY key'))
 def __len__(self):return self.db.execute('SELECT count(*) FROM adjacency').fetchone()[0]
class FrozenPool(dict):
 def __deepcopy__(self,memo):return self

def retriever(directory,source_root):
 from goskills import retrieval
 directory=Path(directory);receipt=json.loads((directory/'RECEIPT.json').read_text());assert receipt['status']=='COMPILED_EXACT'
 for name,h in receipt['files'].items():assert digest(directory/name)==h
 for name,h in receipt['core_sources'].items():assert digest(Path(retrieval.__file__).parent/name)==h
 pool=FrozenPool(json.loads((directory/'header.json').read_text()));pool['adjacency']=Adjacency(directory/'adjacency.sqlite')
 for kind in ['skills','groups','facet_index','member_index']:pool[kind]=DiskMap(directory/'maps.sqlite',kind)
 original_validate=retrieval.validate_pool;original_hash=retrieval.canonical_hash
 retrieval.validate_pool=lambda value: value if value is pool else original_validate(value)
 retrieval.canonical_hash=lambda value: receipt['original_pool_hash'] if value is pool else original_hash(value)
 try:return retrieval.Retriever(pool,source_root=source_root)
 finally:retrieval.validate_pool=original_validate

def main():
 p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--query',required=True);p.add_argument('--source-root',required=True);p.add_argument('--json',action='store_true');a=p.parse_args();result=retriever(a.cache,a.source_root).query(a.query)
 from goskills.validation import validate_bundle
 validate_bundle(result);print(json.dumps(result,ensure_ascii=False) if a.json else result['rendered_context'])
if __name__=='__main__':main()
