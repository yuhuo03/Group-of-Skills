#!/usr/bin/env python3
"""Download a public tar.gz asset into a new directory; default only prints a plan."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,tarfile,tempfile,urllib.request,shutil,os
MAX_BYTES=4*1024**3

def extract(archive, destination, strip=1):
 destination=Path(destination);destination.mkdir(parents=True,exist_ok=False);total=0;seen=set()
 with tarfile.open(archive,'r|gz') as tar:
  for m in tar:
   parts=PurePosixPath(m.name).parts
   if m.name.startswith('/') or '..' in parts:raise ValueError('Unsafe archive path')
   if len(parts)<=strip:continue
   rel=Path(*parts[strip:]);target=destination/rel
   if m.isdir():target.mkdir(parents=True,exist_ok=True);continue
   if not m.isfile():raise ValueError('Only regular files/directories may be extracted')
   if rel in seen:raise ValueError('Duplicate archive member')
   seen.add(rel);total+=m.size
   if total>MAX_BYTES:raise ValueError('Uncompressed asset exceeds4GiB')
   target.parent.mkdir(parents=True,exist_ok=True)
   with target.open('xb') as out:shutil.copyfileobj(tar.extractfile(m),out)
   target.chmod(0o755 if m.mode&0o111 else 0o644)
 return {'files':len(seen),'uncompressed_bytes':total}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',required=True);p.add_argument('--sha256');p.add_argument('--strip-components',type=int,default=1);p.add_argument('--output',type=Path,required=True);p.add_argument('--execute',action='store_true');a=p.parse_args()
 if not a.url.startswith('https://') or a.strip_components<0:p.error('Use HTTPS and nonnegative strip-components')
 if a.output.exists():raise FileExistsError(a.output)
 if not a.execute:print(json.dumps({'status':'DOWNLOAD_PLAN','url':a.url,'expected_sha256':a.sha256,'output':str(a.output),'provider_calls':0}));return
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='asset-download-',dir=a.output.parent) as d:
  archive=Path(d)/'asset.tar.gz';h=hashlib.sha256();n=0
  with urllib.request.urlopen(a.url,timeout=120) as response, archive.open('xb') as out:
   for chunk in iter(lambda:response.read(1024*1024),b''):
    n+=len(chunk)
    if n>MAX_BYTES:raise ValueError('Compressed asset exceeds4GiB')
    h.update(chunk);out.write(chunk)
  if a.sha256 and h.hexdigest()!=a.sha256:raise ValueError('Archive SHA mismatch')
  extracted=Path(d)/'extracted';result=extract(archive,extracted,a.strip_components)
  record={'url':a.url,'archive_sha256':h.hexdigest(),'archive_bytes':n,**result,'hash_pinned':bool(a.sha256)}
  marker=extracted/'DOWNLOAD_RECEIPT.json'
  with marker.open('x') as f:json.dump(record,f,indent=2);f.write('\n')
  # The target is exclusively reserved; move only this download's files.
  a.output.mkdir(exist_ok=False)
  for f in extracted.iterdir():shutil.move(str(f),a.output/f.name)
 print(json.dumps(record))
if __name__=='__main__':main()
