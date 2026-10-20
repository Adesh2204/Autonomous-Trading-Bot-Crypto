"""Inspect retained V6 public request receipts; never modifies account state."""
from pathlib import Path
import hashlib,json,time
O=Path(__file__).resolve().parent
files=[];total=0;violations=[]
for path in sorted(O.rglob('*info_receipts.jsonl')):
 # Public reader source has no copied receipts or private credential files.
 rows=0
 for line in path.read_text().splitlines():
  if not line.strip():continue
  record=json.loads(line);request=record.get('request') or record.get('payload')
  if not isinstance(request,dict) or not isinstance(request.get('type'),str):
   violations.append(dict(file=str(path.relative_to(O)),reason='REQUEST_SCHEMA_UNAVAILABLE'));continue
  if {'action','signature','private_key','nonce'}&set(request) or request['type'] in {'order','cancel','updateLeverage','approveAgent','spotSend','withdraw3'}:
   violations.append(dict(file=str(path.relative_to(O)),reason='NON_INFO_REQUEST'))
  rows+=1
 total+=rows;files.append(dict(file=str(path.relative_to(O)),requests=rows,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
r=dict(observed_ms=time.time_ns()//1000000,scope='Retained V6 info receipt files only; independent of original historical journals and any later human actions',
 files=files,request_count=total,violations=violations,all_public_info_only=not violations,
 authority_created=False)
(O/'public_evidence_verification.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(dict(receipt_files=len(files),request_count=total,violations=violations),indent=2))
raise SystemExit(1 if violations else 0)
