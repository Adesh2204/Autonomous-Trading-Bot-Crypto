"""Requested one-ATR / 0.5% policy, offline SDK fixtures only."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
import pytest
from exchange.reliability_policy import load_reliability_policy
from test_production_reliability import protected, live


@pytest.mark.parametrize('quantity,side,trigger', [('.2', 'A', '93'), ('-.2', 'B', '107')])
def test_one_atr_beyond_normal_stop_with_bounded_half_percent(protected, quantity, side, trigger):
    _, _, policy = load_reliability_policy(ROOT / 'configs/reliability_policy.json')
    assert policy.enabled is False
    # Only this ephemeral test object is enabled. The saved policy remains false.
    protected.manager.policy = replace(policy, enabled=True, approval_reference='OFFLINE_REQUESTED_POLICY_FIXTURE')
    protected.position(quantity)
    before = deepcopy(protected.managed._open_position)
    protected.manager.ensure_all()
    assert protected.manager.report()['positions']['par:BTC']['status'] == 'ACTIVE'
    order = protected.live.fixture.orders[0]
    assert order['side'] == side and Decimal(order['triggerPx']) == Decimal(trigger)
    assert Decimal(order['sz']) == abs(Decimal(quantity)) and order['reduceOnly'] is True
    wire = protected.live.transport.signed_payloads[0]['action']['orders'][0]
    limit = Decimal(wire['p'])
    if side == 'A':
        assert Decimal(trigger) * Decimal('.995') <= limit <= Decimal(trigger)
    else:
        assert Decimal(trigger) <= limit <= Decimal(trigger) * Decimal('1.005')
    assert protected.managed._open_position == before


def test_saved_disabled_configuration_cannot_submit_even_with_realistic_exposure(protected):
    _, _, policy = load_reliability_policy(ROOT / 'configs/reliability_policy.json')
    protected.manager.policy = policy
    protected.manager.ensure_all()
    assert protected.manager.report()['positions']['par:BTC']['status'] == 'ERROR'
    assert protected.live.executor.entries_paused
    assert not protected.live.transport.signed_payloads


def test_one_atr_emergency_trigger_beyond_liquidation_is_refused(protected):
    _, _, policy = load_reliability_policy(ROOT / 'configs/reliability_policy.json')
    protected.manager.policy = replace(policy, enabled=True, approval_reference='OFFLINE_REQUESTED_POLICY_FIXTURE')
    protected.live.fixture.state['assetPositions'][0]['position']['liquidationPx'] = '94'
    protected.manager.ensure_all()
    assert protected.manager.report()['positions']['par:BTC']['status'] == 'ERROR'
    assert protected.live.executor.entries_paused
    assert not protected.live.transport.signed_payloads
