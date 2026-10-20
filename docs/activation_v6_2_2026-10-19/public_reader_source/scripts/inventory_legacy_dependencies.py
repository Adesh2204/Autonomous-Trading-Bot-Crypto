"""Classify every legacy-term occurrence in non-secret repository source files.

Dispositions describe migration intent, not a claim that every legacy file has
already been deleted. Context text and credential values are never exported.
"""
from collections import Counter
import csv
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
# Include identifier prefixes (NSEMarketSchedule, NOT_NSE, totp_code), while
# avoiding unrelated words such as CONSECUTIVE and info.
PATTERN = re.compile(r'SmartAPI|SmartConnect|Angel\s+One|NSE_CM|NSE_FO|'
                     r'(?<![A-Za-z0-9])(?:NSE|NFO|TOTP)(?=(?-i:[A-Z])|[^A-Za-z]|$)|'
                     r'symboltoken|exchangeType|feedToken|authToken|refreshToken|clientCode', re.I)
GENERATED = {'docs/legacy_dependency_inventory.csv', 'docs/legacy_dependency_inventory.json'}
TEXT_SUFFIXES = {'.py', '.md', '.txt', '.json', '.xml', '.cpp', '.hpp', '.h', '.toml',
                 '.ini', '.cfg', '.yaml', '.yml', '.example', ''}
REPLACEMENTS = {
    'live_stream.py': 'exchange.hyperliquid_market_data public streams; exchange.hyperliquid_client',
    'backtest_engine.py': 'exchange.hyperliquid_market_data candles; frozen_strategy input adapter',
    'historical_data.py': 'UTC closed-candle schema in exchange.base_exchange',
    'history_service.py': 'HyperliquidMarketData.get_candles',
    'session_bootstrap.py': 'ParMarketDataEngine.reconcile_history',
    'instrument_registry.py': 'HyperliquidClient.startup and MarketSpec',
    'market_discovery.py': 'verified par runtime universe',
    'premarket_screener.py': 'MarketRegimeScanner periodic runtime par selection',
    'opportunity_engine.py': 'dimensionless cross-section percentile selection; UTC liquidity diagnostics',
    'discovery_data.py': 'HyperliquidClient public metadata',
    'market_universe.py': 'verified par runtime universe',
    'execution_adapters.py': 'HyperliquidExecution / PaperExecution',
    'execution_safety.py': 'MarketSpec; perpetual_economics; risk.PortfolioRisk; paper USDPR ledger',
    'execution_engine.py': 'generic execution interfaces; retain frozen management logic',
    'safe_trader.py': 'generic execution/account/reconciliation; retain frozen strategy methods',
    'runtime_observation.py': 'generic quote/candle inputs; retain frozen signal and direction rules',
    'market_schedule.py': 'SessionManager continuous UTC daily adapter',
    'candle_builder.py': 'closed Hyperliquid Candle input',
    'symbol_state.py': 'par symbol and generic MarketSpec identity',
    'replay_engine.py': 'generic shared-capital crypto replay (later migration)',
    'research_harness.py': 'generic shared-capital crypto research (later migration)',
    'refresh_instruments.py': 'HyperliquidClient.startup runtime metadata',
    'tick_parser.hpp': 'provider-neutral market data schema',
}


def classify(relative, line, term):
    path = Path(relative)
    name = path.name
    if name.startswith('test') or name == 'safety_test_support.py':
        return 'KEEP AS LEGACY REFERENCE', 'offline regression fixtures; never used by the new data runner'
    if relative.startswith('docs/') or path.suffix == '.md' or name.startswith('inventory_'):
        return 'KEEP AS LEGACY REFERENCE', 'historical evidence or migration documentation'
    if name in {'disabled_angel_client.py', 'order_guard.py', 'phase0_check.py', 'requirements-legacy.txt'}:
        return 'KEEP AS LEGACY REFERENCE', 'permanent lockout, safety check or optional legacy dependencies'
    if name == 'signal_brain.py':
        return 'KEEP AS LEGACY REFERENCE', 'frozen strategy; adapt input instead of changing formulas'
    if name == 'config.py':
        return 'REMOVE', 'retired stock defaults; new core uses venue_config and runtime MarketSpec'
    if re.fullmatch(r'NFO|NSE_FO|TOTP|clientCode|authToken|refreshToken|feedToken', term, re.I):
        return 'REMOVE', 'retired login/session/segment coupling; no credentials in the new public data path'
    return 'REPLACE', REPLACEMENTS.get(name, 'par market identity and generic exchange interfaces')


def main():
    raw = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                         cwd=ROOT, capture_output=True, check=True).stdout
    paths = sorted(set(raw.decode().split('\0')) - {''})
    occurrences = []
    skipped = []
    for relative in paths:
        path = ROOT/relative
        if (relative in GENERATED or not path.is_file() or path.suffix not in TEXT_SUFFIXES
                or path.name == '.env' or path.name.startswith('.env.') and path.name != '.env.example'):
            skipped.append(relative)
            continue
        try:
            lines = path.read_text().splitlines()
        except UnicodeError:
            skipped.append(relative)
            continue
        for number, line in enumerate(lines, 1):
            for match in PATTERN.finditer(line):
                disposition, replacement = classify(relative, line, match.group())
                occurrences.append(dict(path=relative, line=number, column=match.start()+1,
                    term=match.group(), disposition=disposition, replacement=replacement,
                    status='reference_retained; excluded from new exchange core'))
    csv_path = ROOT/'docs/legacy_dependency_inventory.csv'
    with csv_path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, lineterminator='\n', fieldnames=['path', 'line', 'column', 'term',
            'disposition', 'replacement', 'status'])
        writer.writeheader()
        writer.writerows(occurrences)
    summary = dict(occurrences=len(occurrences),
        files_with_occurrences=len({row['path'] for row in occurrences}),
        disposition_counts=dict(Counter(row['disposition'] for row in occurrences)),
        exclusions=skipped, note='Source locations and matched terms only; no credential values or line contents.',
        generated_reports_excluded_to_avoid_self_inventory=True)
    (ROOT/'docs/legacy_dependency_inventory.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps({key: summary[key] for key in ('occurrences', 'files_with_occurrences', 'disposition_counts')}))


if __name__ == '__main__':
    main()
