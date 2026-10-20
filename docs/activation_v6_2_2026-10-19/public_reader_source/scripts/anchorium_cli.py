"""Standalone Anchorium operator terminal. Defaults to public observation."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
# Never load dotenv secrets during diagnostics, proposals or public observation.
os.environ['ANCHORIUM_PUBLIC_ONLY'] = 'true'

if __name__ == '__main__':
    from exchange.terminal_app import main
    raise SystemExit(main(ROOT))
