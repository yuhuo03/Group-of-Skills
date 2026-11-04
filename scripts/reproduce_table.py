#!/usr/bin/env python3
"""Recompute all 45 metric cells from the 1,545 selected trial rows. No API calls."""
import argparse,csv,json,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
METHODS=[('noskills','No Skills'),('vanilla','Vanilla Skills'),('vector','Vector Skills'),('native-gos','Graph of Skills'),('goskills-d','GoSkills (D)')]
BENCHES=[('skillsbench',86,'SB Reward (%)','SB Tokens','SB Runtime (s)'),('alfworld',134,'ALF Success (%)','ALF Tokens','ALF Runtime (s)'),('tb2',89,'TB2 Accuracy (%)','TB2 Tokens','TB2 Runtime (s)')]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--check',action='store_true');ap.add_argument('--output',type=Path);a=ap.parse_args();rows=list(csv.DictReader((ROOT/'data/selected_trials.csv').open()));assert len(rows)==1545 and len({x['id'] for x in rows})==1545
 table=[]
 for m,label in METHODS:
  r={'Method':label}
  for b,n,score,tokens,runtime in BENCHES:
   xs=[x for x in rows if x['benchmark']==b and x['method']==m];assert len(xs)==n,(b,m,len(xs));assert len({x['task'] for x in xs})==n
   r[score]=statistics.mean(float(x['reward']) for x in xs)*100;r[tokens]=statistics.mean(int(x['input_tokens']) for x in xs);r[runtime]=statistics.mean(float(x['runtime_seconds']) for x in xs)
  r['TB2 runtime n']=89;table.append(r)
 if a.check:
  expected=list(csv.DictReader((ROOT/'tables/TABLE.csv').open()));assert len(expected)==5
  for r,e in zip(table,expected):
   assert r['Method']==e['Method']
   for k in r:
    if k!='Method':assert abs(float(r[k])-float(e[k]))<1e-8,(r['Method'],k,r[k],e[k])
  print('PASS: all 1,545 rows and 45 metric cells match the selected table.')
 if a.output:
  with a.output.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
 if not a.check and not a.output:print(json.dumps(table,indent=2))
if __name__=='__main__':main()
