"""Create a secret-free read-only readiness/evidence index; never activate trading."""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from certification_audit import build_audit,write_audit


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests-xml',type=Path)
    parser.add_argument('--tests-receipt',type=Path)
    parser.add_argument('--market-evidence',type=Path)
    parser.add_argument('--session',type=Path,action='append',default=[])
    parser.add_argument('--research-evidence',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    report=build_audit(ROOT,tests_xml=args.tests_xml,tests_receipt=args.tests_receipt,
        market_evidence=args.market_evidence,sessions=args.session,research_evidence=args.research_evidence)
    path=write_audit(report,args.output)
    print(report['verdict']+'; LIVE_READY=FALSE; HACKATHON_READY=FALSE; report='+str(path.resolve()))
    return 1 if report['verdict']=='NOT_READY' else 0


if __name__=='__main__':raise SystemExit(main())
