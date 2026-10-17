"""Repair copied activation paths only within this clone; install nothing."""
from pathlib import Path
import hashlib,json,re
root=Path(__file__).resolve().parents[2];venv=root/'.venv'
if venv.resolve().parent!=root:raise RuntimeError('LOCAL_CLONE_VENV_REQUIRED')
text=(venv/'bin/activate').read_text();match=re.search(r"^VIRTUAL_ENV='([^']+)'$",text,re.M)
if not match:raise RuntimeError('REVIEW_UNEXPECTED_ACTIVATION_FORMAT')
previous=match.group(1);rows=[]
for name in ('activate','activate.csh','activate.fish'):
 p=venv/'bin'/name;before=p.read_bytes();after=before.decode().replace(previous,str(venv)).encode()
 if after!=before:p.write_bytes(after)
 rows.append(dict(file=str(p.relative_to(root)),before_sha256=hashlib.sha256(before).hexdigest(),after_sha256=hashlib.sha256(after).hexdigest()))
out=Path(__file__).with_name('activation_repair_receipt.json')
if out.exists():raise RuntimeError('PRESERVE_EXISTING_ACTIVATION_RECEIPT')
out.write_text(json.dumps(dict(previous_prefix=previous,current_prefix=str(venv),packages_installed=0,original_repository_modified=False,files=rows),indent=2)+'\n')
print(json.dumps(dict(repaired=True,prefix=str(venv),packages_installed=0)))
