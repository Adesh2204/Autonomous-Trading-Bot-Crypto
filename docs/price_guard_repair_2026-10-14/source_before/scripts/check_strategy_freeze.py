"""Verify the frozen strategy without credentials, network, or broker SDKs."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'algo-trading-bot'))
from strategy_freeze import verify_strategy_freeze


if __name__ == '__main__':
    print(json.dumps(verify_strategy_freeze(), indent=2))
