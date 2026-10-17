"""Capture public primary rule pages for evidence; no exchange endpoint/client."""
from pathlib import Path
import requests,hashlib,json,time
from urllib.parse import urlparse
P=Path(__file__).resolve().parent;out=P/'primary_rule_sources';out.mkdir(exist_ok=False)
urls={
 'par_guide.html':'https://perpetual-alpha26.github.io/docs/',
 'error_responses.md':'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses.md',
 'native_tpsl.md':'https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl.md',
 'exchange_schema.md':'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint.md',
 'order_types.md':'https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types.md',
 'hypercore_order_book.md':'https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/order-book.md',
 'tpsl_support.md':'https://hyperliquid.gitbook.io/hyperliquid-docs/support/faq/trade-outcome-looks-incorrect/my-tp-sl-did-not-execute-correctly.md'}
rows=[]
for name,url in urls.items():
 try:
  r=requests.get(url,timeout=20);r.raise_for_status()
  if urlparse(r.url).hostname not in {'hyperliquid.gitbook.io','perpetual-alpha26.github.io'} or len(r.content)>2000000:raise ValueError('PRIMARY_CAPTURE_BOUND')
  (out/name).write_bytes(r.content);rows.append(dict(url=url,final_url=r.url,file=name,status=r.status_code,bytes=len(r.content),sha256=hashlib.sha256(r.content).hexdigest(),observed_ms=time.time_ns()//1000000))
 except Exception as e:rows.append(dict(url=url,error=type(e).__name__,reason=str(e)))
(out/'manifest.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(rows,indent=2))
