"""Safe immutable research artifacts and append-only attempt evidence."""
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import subprocess

ROOT = Path(__file__).resolve().parents[2]
MARKETS = ('par:BTC','par:ETH','par:HYPE','par:SP500','par:EWY','par:EWJ',
           'par:BRENT','par:GOLD','par:USDEUR','par:USDJPY')


class ResearchError(ValueError):
    pass


def canonical(value):
    def encode(v):
        if is_dataclass(v): return asdict(v)
        if hasattr(v, 'item'): return v.item()
        raise TypeError('NON_JSON_RESEARCH_ARTIFACT')
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, default=encode)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def finite(value):
    if isinstance(value, bool): raise ResearchError('BOOLEAN_NOT_NUMERIC')
    try: result = float(value)
    except (TypeError, ValueError) as exc: raise ResearchError('INVALID_NUMBER') from exc
    if not math.isfinite(result): raise ResearchError('NONFINITE_NUMBER')
    return result


def stamp(value):
    if type(value) is not int or value < 0: raise ResearchError('TIMESTAMP_REQUIRED')
    return value


def utc_day(ms):
    return datetime.fromtimestamp(stamp(ms)/1000, timezone.utc).date().isoformat()


def immutable_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation: previous model/run evidence is never silently replaced.
    with path.open('x') as f: f.write(json.dumps(value, indent=2, default=lambda v: json.loads(canonical(v)), allow_nan=False)+'\n')


def source_identity():
    paths = list((ROOT/'algo-trading-bot/research_intelligence').glob('*.py'))
    paths += [ROOT/'algo-trading-bot/signal_brain.py', ROOT/'docs/strategy_freeze.json']
    paths += list((ROOT/'research/configurations').glob('*.json'))
    paths += [ROOT/'scripts/run_strategy_intelligence_research.py']
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
    return dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                source_hash=digest(hashes), file_sha256=hashes,
                dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()))


def record_attempt(path, event):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f: f.write(canonical(event)+'\n')


class HoldoutLedger:
    """Seal a held-out dataset against later specification changes in one registry."""
    def __init__(self, directory):
        self.directory = Path(directory); self.directory.mkdir(parents=True, exist_ok=True)

    def claim(self, holdout_identity, specification):
        path = self.directory/(digest(holdout_identity)+'.json')
        record = dict(holdout_identity=holdout_identity, specification_hash=digest(specification))
        if path.exists():
            previous = json.loads(path.read_text())
            if previous != record: raise ResearchError('HOLDOUT_ALREADY_SEALED_FOR_DIFFERENT_SPECIFICATION')
            return False  # Identical reproducibility verification, never a new tuning attempt.
        immutable_json(path, record)
        return True
