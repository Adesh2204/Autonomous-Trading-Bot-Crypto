"""Validate local reference CSVs and prepare isolated research; never activate trading."""
import argparse
import csv
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze
from research_intelligence.common import ResearchError, immutable_json, source_identity
from research_intelligence.organizer_history import (DATA_ROOT, HistoricalDataset,
    validate_directory, inspect_archive)
from research_intelligence.reference_price_analysis import chronological_price_analysis


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--history-directory', type=Path, default=DATA_ROOT)
    p.add_argument('--archive', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--features-output', type=Path)
    args = p.parse_args()
    require_paper_migration()
    freeze = verify_strategy_freeze()
    if args.output.exists():
        p.error('output must be new; preserve previous evidence')
    feature_root = ROOT / 'algo-trading-bot/data/organizer-history-research'
    if args.features_output and (not args.features_output.resolve().is_relative_to(feature_root.resolve()) or
            any(parent.is_symlink() for parent in args.features_output.parents)):
        p.error('raw features must stay inside the dedicated organizer-history-research data directory')
    args.output.mkdir(parents=True)
    validation = validate_directory(args.history_directory)
    immutable_json(args.output / 'csv_validation.json', validation)
    fields = ('market', 'rows', 'start_timestamp', 'end_timestamp', 'missing_rows', 'duplicates', 'invalid_values', 'status')
    with (args.output / 'csv_validation.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader(); writer.writerows(validation['markets'])
    if args.archive:
        try:
            archive = inspect_archive(args.archive)
        except (ResearchError, zipfile.BadZipFile, OSError) as exc:
            archive = dict(status='REJECTED', reason=str(exc), extraction_performed=False)
    else:
        archive = dict(status='NOT_AVAILABLE', reason='No original ZIP found; original archive safety cannot be certified.',
                       extraction_performed=False)
    immutable_json(args.output / 'archive_safety.json', archive)
    report = dict(execution_mode='PAPER', allow_live_orders=False, exchange_orders_submitted=0,
        strategy_freeze=freeze, source=source_identity(), validation=validation, archive=archive,
        history_data_ready=False, research_data_ready=False, official_provenance_verified=False,
        schema_valid=validation['schema_valid'], price_feature_research_prepared=False,
        controlled_live_test='NOT RUN — NOT LIVE VERIFIED')
    if validation['schema_valid']:
        analysis, features = chronological_price_analysis(HistoricalDataset(args.history_directory))
        immutable_json(args.output / 'price_analysis.json', analysis)
        report['price_feature_research_prepared'] = True
        report['feature_rows'] = len(features)
        if args.features_output:
            args.features_output.parent.mkdir(parents=True, exist_ok=True)
            with args.features_output.open('x') as stream:
                for row in features:
                    stream.write(json.dumps(row, allow_nan=False) + '\n')
            report['features_path'] = str(args.features_output.resolve())
    report['readiness_note'] = 'Local structure/price research can pass; official provenance, one-minute strategy compatibility and executable ML outcomes remain separate.'
    immutable_json(args.output / 'history_verification.json', report)
    print(json.dumps(dict(output=str(args.output.resolve()), schema_valid=validation['schema_valid'],
        total_rows=validation['total_rows'], features=report.get('feature_rows'),
        official_provenance_verified=False, exchange_orders_submitted=0)))
    return 0 if validation['schema_valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
