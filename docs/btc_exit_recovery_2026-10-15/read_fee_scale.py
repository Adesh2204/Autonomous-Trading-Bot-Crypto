from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.hyperliquid_client import HyperliquidClient
from exchange.paper_operations import atomic_json
c=HyperliquidClient()
try:
 rows=c.post_info('perpDexs');par=[r for r in rows if isinstance(r,dict) and r.get('name')=='par']
 atomic_json(Path(__file__).with_name('dex_fee_evidence.json'),dict(observed_ms=c.clock_ms(),rows=par,signatures=0,orders=0))
 print(json.dumps(par,indent=2)[:1200])
finally:c.close()
