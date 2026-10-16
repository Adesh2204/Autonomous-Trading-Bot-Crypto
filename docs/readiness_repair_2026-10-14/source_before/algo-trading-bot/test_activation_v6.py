from datetime import timedelta
import json
import pytest
import config
from activation_gate import validate_activation
from test_safety_v6 import NOW
from safety_test_support import live_trader
from execution_engine import PaperTrader
from execution_safety import SafetyError


def test_flags_alone_cannot_enable_live(tmp_path,monkeypatch):
    trader,broker=live_trader(tmp_path,monkeypatch)
    adapter=trader.adapter
    trader.shutdown()
    monkeypatch.setattr(config,'LIVE_ACTIVATION_EVIDENCE_FILE',None)
    with pytest.raises(SafetyError,match='EVIDENCE'):
        PaperTrader(environment='LIVE',adapter=adapter,clock=lambda:NOW,csv_log_path=str(tmp_path/'other.csv'))
    assert not broker.requests


@pytest.mark.parametrize('mutation',['code','expired','failed_test','broker_check','p0_check','paper_only'])
def test_invalid_activation_evidence_cannot_enable(mutation,tmp_path,monkeypatch):
    trader,_=live_trader(tmp_path,monkeypatch)
    path=config.LIVE_ACTIVATION_EVIDENCE_FILE
    trader.shutdown()
    with open(path) as file:evidence=json.load(file)
    if mutation=='code':evidence['source_fingerprint']='wrong'
    elif mutation=='expired':evidence['verified_until']=(NOW-timedelta(seconds=1)).isoformat()
    elif mutation=='failed_test':evidence['tests']['failed']=1
    elif mutation=='broker_check':evidence['broker_checks']['observed_emergency_flatten']='UNVERIFIED'
    elif mutation=='p0_check':evidence['p0_checks']['confirmed_fills']='FAIL'
    else:evidence['recommendation']='PAPER_ONLY'
    with open(path,'w') as file:json.dump(evidence,file)
    with pytest.raises(SafetyError,match='EVIDENCE'):validate_activation(path,NOW)
