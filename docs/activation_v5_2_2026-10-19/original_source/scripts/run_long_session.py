"""Separate exact-approved TESTNET LONG command. Public observation never signs."""
import argparse,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mandate',required=True);p.add_argument('--acceptance',required=True)
    p.add_argument('--release',required=True);p.add_argument('--native-protection-evidence',required=True)
    a=p.parse_args()
    # Skip dotenv wallet settings until the exact-approved builder explicitly
    # calls the existing signer loader after all evidence gates have passed.
    os.environ['ANCHORIUM_PUBLIC_ONLY']='true'
    from decimal import Decimal as D
    from market_regime_scanner import ScannerPolicy
    from risk.models import RiskPolicy
    from exchange.long_session import build_long_runtime,read_mandate
    m=read_mandate(a.mandate)
    # Original frozen scanner/state limits. No per-observation operator commands.
    scanner=ScannerPolicy(D('.004'),D(m.maximum_spread_bps),D(0),D(10),history_bars=300,top_n=3)
    risk=RiskPolicy(D(m.daily.risk_fraction),D(m.daily.daily_loss_fraction),D(1),D('.5'),D(2),D('.001'),
        D(50),D(m.maximum_spread_bps),D(m.depth_participation),D(m.execution_slippage_bps),D(1),1)
    runtime=build_long_runtime(ROOT,a.mandate,a.acceptance,a.release,a.native_protection_evidence,
        scanner_policy=scanner,risk_policy=risk)
    runtime.run()

if __name__=='__main__':main()
