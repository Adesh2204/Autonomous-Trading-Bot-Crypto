"""Fetch only the two data URLs declared by the saved official leaderboard."""
from pathlib import Path
import hashlib,json,re,time,requests
out=Path(__file__).resolve().parent/'public_registration_review'
html=(out/'leaderboard.html').read_text()
line=next(x for x in html.splitlines() if 'const URLS =' in x)
urls=re.findall(r'"(https://[^\"]+\.json)"',line)
result=[]
for url in urls:
 r=requests.get(url,timeout=20)
 row=dict(url=url,status_code=r.status_code,observed_ms=time.time_ns()//1000000,sha256=hashlib.sha256(r.content).hexdigest())
 if r.ok:
  data=r.json();(out/Path(url).name).write_text(json.dumps(data,indent=2)+'\n')
  row['root_keys']=list(data) if isinstance(data,dict) else None
  matches=[]
  def visit(v):
   if isinstance(v,dict):
    flat=json.dumps({k:x for k,x in v.items() if not isinstance(x,(dict,list))}).lower()
    if any(s in flat for s in ('anchorium','0x94ea16ece139e246a1d84e71aacf7dd1f47cb12c','0xe590711084f687d278516f4882c075a862cd73cb')):matches.append(v)
    for x in v.values():visit(x)
   elif isinstance(v,list):
    for x in v:visit(x)
  visit(data);row['matches']=matches
 else:row['response_excerpt']=r.text[:200]
 result.append(row)
(out/'data_review.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
