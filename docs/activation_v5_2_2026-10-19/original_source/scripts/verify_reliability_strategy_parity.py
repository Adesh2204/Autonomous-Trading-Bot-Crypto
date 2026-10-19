"""Compare pre-hardening and current frozen brain on identical offline inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
import numpy as np
import pandas as pd
from signal_brain import generate_vwap_signal
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration


def validate(before_ref='519d6763d277a66c80cac26ba4b114c4dbb98ad5'):
    require_paper_migration()
    freeze=verify_strategy_freeze()
    before=subprocess.check_output(['git','show',before_ref+':algo-trading-bot/signal_brain.py'],cwd=ROOT)
    current=(ROOT/'algo-trading-bot/signal_brain.py').read_bytes()
    if before!=current:
        raise AssertionError('PROTECTED_BRAIN_CHANGED')
    namespace={'__name__':'anchorium_pre_hardening_brain'}
    exec(compile(before,'pre_hardening_signal_brain.py','exec'),namespace)
    rng=np.random.default_rng(41003)
    rows=[]
    fixtures=[('warmup',10,'flat'),('flat',120,'flat'),('uptrend',360,'up'),
        ('downtrend',360,'down'),('volatile',720,'volatile'),('UTC_day_boundary',480,'volatile')]
    for name,n,kind in fixtures:
        x=np.arange(n)
        trend=x*.015 if kind=='up' else -x*.015 if kind=='down' else x*0
        close=100+trend+(np.sin(x/9)*.7 if kind!='flat' else np.sin(x/9)*.03)
        if kind=='volatile':
            close+=np.cumsum(rng.normal(0,.1,n))
        opens=np.r_[close[0],close[:-1]]
        volume=rng.uniform(100,1000,n)
        volume[::17]*=4
        start='2026-10-01 22:00:00+00:00' if name=='UTC_day_boundary' else '2026-10-02 00:00:00+00:00'
        frame=pd.DataFrame(dict(Timestamp=pd.date_range(start,periods=n,freq='min'),
            Open=opens,High=np.maximum(opens,close)+.1,Low=np.minimum(opens,close)-.1,
            Close=close,Volume=volume))
        a=namespace['generate_vwap_signal'](frame.copy(deep=True))
        b=generate_vwap_signal(frame.copy(deep=True))
        pd.testing.assert_frame_equal(a,b,check_exact=True)
        digest=hashlib.sha256(pd.util.hash_pandas_object(b,index=True).values.tobytes()).hexdigest()
        signals={c:int(b[c].fillna(False).astype(bool).sum()) for c in b.columns if c.endswith('_Signal')}
        rows.append(dict(fixture=name,input_rows=n,output_rows=len(b),output_columns=len(b.columns),
                         outputs_identical=True,output_sha256=digest,signals=signals))
    return dict(before_ref=before_ref,strategy_freeze=freeze,protected_source_identical=True,
        signal_brain_sha256=hashlib.sha256(current).hexdigest(),fixtures=rows,
        total_input_rows=sum(r['input_rows'] for r in rows),passed=True,exchange_orders_submitted=0,
        scope='Synthetic indicator/signal parity; separate regression tests verify frozen stop/target/cooldown behavior.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-ref',default='519d6763d277a66c80cac26ba4b114c4dbb98ad5')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=validate(args.before_ref)
    encoded=json.dumps(result,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(encoded)
    print(encoded)


if __name__=='__main__':
    main()
