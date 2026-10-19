"""PAPER-only denied-signal excursions; no execution adapter and no trade ledger."""
from pathlib import Path
import json
import pandas as pd
import config


class ShadowDiagnostics:
    def __init__(self,directory):
        if config.LIVE_MODE:
            raise ValueError('PAPER_SHADOW_ONLY')
        self.directory=Path(directory)/'shadow'
        self.directory.mkdir(parents=True,exist_ok=True)
        self.events={}

    def record(self,observation):
        if not observation.signal_generated or observation.executable:
            return
        if observation.signal_id in self.events:
            return
        row=observation.report()|{'research_only':True,'credited_pnl':0,'basis':'DENIED_SIGNAL_OBSERVATION'}
        self.events[observation.signal_id]=row
        with (self.directory/'observations.jsonl').open('a') as file:
            file.write(json.dumps(row,default=str)+'\n')

    def finish(self,states):
        outcomes=[]
        for event in self.events.values():
            state=states.get(event['token'])
            if state is None or state.builder.df.empty or event['reference_entry'] is None:
                continue
            frame=state.builder.df
            after=frame.loc[frame.Timestamp>pd.Timestamp(event['candle_timestamp'])]
            if after.empty:
                continue
            ref=event['reference_entry']
            sign=1 if event['side']=='BUY' else -1
            favorable=(float(after.High.max())-ref) if sign==1 else (ref-float(after.Low.min()))
            adverse=(float(after.Low.min())-ref) if sign==1 else (ref-float(after.High.max()))
            outcomes.append({'symbol':event['symbol'],'timestamp':event['candle_timestamp'],
                'blocking_reasons':event['blocking_reasons'],'maximum_favorable_price_move':favorable,
                'maximum_adverse_price_move':adverse,'credited_pnl':0,
                'basis':'POST_SESSION_CANDLE_EXCURSIONS; NO FILLS, NO NET PROFIT CLAIM'})
        path=self.directory/'outcomes.json'
        path.write_text(json.dumps({'research_only':True,'production_pnl_credited':0,'outcomes':outcomes},indent=2))
        return path
