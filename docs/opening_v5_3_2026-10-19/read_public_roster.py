"""Read only the official public leaderboard page and its declared script sources."""
from pathlib import Path
from urllib.parse import urljoin,urlparse
import hashlib,json,re,requests
out=Path(__file__).resolve().parent/'public_registration_review';out.mkdir(exist_ok=False)
base='https://perpetual-alpha26.github.io/leaderboard'
r=requests.get(base,timeout=20);r.raise_for_status();(out/'leaderboard.html').write_text(r.text)
rows=[]
for src in re.findall(r'<script[^>]+src=[\"\']([^\"\']+)',r.text):
 url=urljoin(base,src)
 if urlparse(url).hostname!='perpetual-alpha26.github.io':continue
 reply=requests.get(url,timeout=20);reply.raise_for_status();name=Path(urlparse(url).path).name
 (out/name).write_text(reply.text)
 rows.append(dict(url=url,sha256=hashlib.sha256(reply.content).hexdigest(),candidate_data_paths=[line.strip()[:1000] for line in reply.text.splitlines() if any(k in line for k in ('fetch(','.json','API_URL','apiBase','wallet'))][:60]))
(out/'sources.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(rows,indent=2))
