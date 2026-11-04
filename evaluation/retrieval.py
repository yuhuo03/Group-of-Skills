"""Portable GoSkills retrieval interface shared by all three benchmarks.

Regular JSON pools are convenient locally. Compiled pools preserve the historical
read-only disk-map loading path; neither form changes scoring or presentation.
"""
from pathlib import Path
from goskills.io import read_json
from goskills.config import canonical_hash
from goskills.retrieval import Retriever
from goskills.validation import validate_bundle
from goskills_eval.source_gate import validate_frozen_sources
from goskills_eval.utils import write

class DContext:
 def __init__(self,pool,source_root='/opt/graphskills/skills'):
  path=Path(pool);self.source_root=source_root
  if path.is_dir():
   from goskills_eval.compiled_pool import retriever
   self.retriever=retriever(path,source_root)
   self.pool_hash=read_json(path/'RECEIPT.json')['original_pool_hash']
  else:
   p=read_json(path);self.pool_hash=canonical_hash(p);self.retriever=Retriever(p,source_root=source_root)
 def query(self,text,directory=None):
  bundle=self.retriever.query(text);validate_bundle(bundle)
  validate_frozen_sources(bundle,self.retriever.pool,self.pool_hash,self.source_root)
  if directory is not None:write(Path(directory)/'bundle.json',bundle,True)
  return bundle

def main():
 import argparse,json
 p=argparse.ArgumentParser();p.add_argument('--pool',required=True);p.add_argument('--source-root',default='/opt/graphskills/skills');p.add_argument('--query',required=True);p.add_argument('--output');a=p.parse_args()
 b=DContext(a.pool,a.source_root).query(a.query)
 if a.output:write(a.output,b,True)
 print(b['rendered_context'])
if __name__=='__main__':main()
