#!/usr/bin/env python3
"""Summarize committed VALID receipts, with identity/hash checks and portable paths."""
from pathlib import Path
import argparse,csv,hashlib,json,math,statistics

def collect(root):
 root=Path(root).resolve();plan=json.loads((root/'PLAN.json').read_text());rows=[];groups={};seen=set()
 status_path=root/'STATUS.json';state=json.loads(status_path.read_text()) if status_path.is_file() else {'rows':[]}
 states={}
 for item in state['rows']:
  key=tuple(item[k] for k in ['benchmark','method','task'])
  if key in states:raise ValueError('Duplicate status row')
  states[key]=item
 for job in plan['jobs']:
  key=tuple(job[k] for k in ['benchmark','method','task'])
  if key in seen:raise ValueError('Duplicate planned trial')
  seen.add(key)
  relative=Path(job['output_relative'])
  if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe planned output path')
  p=(root/relative/'receipt.json').resolve()
  if not p.is_relative_to(root):raise ValueError('Receipt escapes campaign directory')
  committed=states.get(key,{})
  if not p.is_file():r={'status':'NOT_FINISHED'}
  else:
   raw=p.read_bytes();r=json.loads(raw)
   if r.get('status')=='VALID':
    if committed.get('status')!='VALID' or committed.get('output_relative')!=relative.as_posix() or hashlib.sha256(raw).hexdigest()!=committed.get('receipt_sha256') or r.get('method')!=job['method']:
     raise ValueError('Uncommitted, changed, or misattributed receipt: '+relative.as_posix())
  row={k:job[k] for k in ['benchmark','method','task']};row['status']=r.get('status','INVALID_RECEIPT')
  if row['status']=='VALID':
   for k in ['reward','input_tokens','output_tokens','runtime_seconds']:
    v=r.get(k)
    if type(v) not in (int,float) or not math.isfinite(v) or v<0:raise ValueError('Invalid or missing metric '+k+' in '+str(p))
    if k.endswith('_tokens') and type(v) is not int:raise ValueError('Token count must be an integer')
    row[k]=v
   if row['reward']>1:raise ValueError('Reward outside [0,1]')
  rows.append(row);groups.setdefault((row['benchmark'],row['method']),[]).append(row)
 if set(states)-seen:raise ValueError('Status contains unplanned trials')
 summary=[]
 for (b,m),xs in sorted(groups.items()):
  valid=[x for x in xs if x['status']=='VALID'];n=len(valid)
  summary.append({'benchmark':b,'method':m,'expected':len(xs),'valid':n,'unresolved':len(xs)-n,'complete':n==len(xs),'score_percent':statistics.mean(x['reward'] for x in valid)*100 if n==len(xs) else None,'mean_input_tokens':statistics.mean(x['input_tokens'] for x in valid) if n==len(xs) else None,'mean_output_tokens':statistics.mean(x['output_tokens'] for x in valid) if n==len(xs) else None,'mean_runtime_seconds':statistics.mean(x['runtime_seconds'] for x in valid) if n==len(xs) else None})
 return rows,summary

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();rows,summary=collect(a.run);a.output.mkdir(parents=True,exist_ok=False)
 for name,data in [('TRIALS.csv',rows),('SUMMARY.csv',summary)]:
  keys=list(dict.fromkeys(k for r in data for k in r))
  with (a.output/name).open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(data)
 (a.output/'SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
