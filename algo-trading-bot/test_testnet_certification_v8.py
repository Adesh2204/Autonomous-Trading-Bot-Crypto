"""OFFLINE_FIXTURE only: ephemeral SDK signatures, exchange HTTP prohibited."""
from copy import deepcopy
from dataclasses import replace, asdict
from decimal import Decimal as D
import json
from types import SimpleNamespace
import pytest

from exchange.base_exchange import ExchangeError
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import LiveAuthorization
from exchange.certification_runtime import CertificationRecovery, CertificationContextProvider
from exchange.order_lifecycle import OrderRequest
from exchange.testnet_certification import (CertificationProposal, CertificationApproval,
    CertificationAuthorization, CertificationSequence, CertificationProtection,
    propose, test_permission as cert_permission, certify_realized, CertificationSDKTransport, require_safe_partial_path)
from test_live_exchange_execution import live, response
from test_exchange_migration import NOW, TEAM


@pytest.fixture
def cert(live, monkeypatch):
    import exchange.testnet_certification as mod
    monkeypatch.setattr(mod, 'TEAM', TEAM)
    monkeypatch.setattr(mod, 'API', live.signer.address)
    # Fixtures still derive the same real SDK wire against a synthetic venue.
    req = OrderRequest('par:BTC', 'BUY', '.2', '100', tif='Ioc')
    ctx = live.provider.load(req)
    p = propose(ctx, live.client, 'fixture-source', reliability_policy_hash='fixture-policy')
    p = replace(p, team_wallet=TEAM, api_wallet=live.signer.address).require()
    a = CertificationApproval(p.identity, 'SYNTHETIC_OPERATOR_ONLY', NOW, NOW+300000, True, True, True)
    auth = CertificationAuthorization(p, a, live.journal, clock_ms=lambda:live.fixture.now,
                                      source_hash=lambda:'fixture-source', policy_hash=lambda:'fixture-policy')
    recovery = CertificationRecovery(live.account, live.journal, initial_start_ms=NOW)
    live.executor.recovery = recovery
    live.provider.reconciliation_ready = lambda:getattr(recovery,'account_truth_ready',False)
    CertificationProtection(live.executor, p)
    v = FakeCertificationVenue(live, monkeypatch, auth)
    return SimpleNamespace(live=live, proposal=p, approval=a, auth=auth, venue=v,
                           sequence=CertificationSequence(live.executor, p, auth))


class FakeCertificationVenue:
    def __init__(self, live, monkeypatch, auth):
        self.l, self.auth, self.statuses = live, auth, {}
        self.oid, self.partial_entry, self.partial_exit = 100, D(1), D(1)
        self.fail, self.cancel_uncertain, self.rest_down = None, False, False
        self.calls = []
        live.client.transport = self.read
        monkeypatch.setattr(live.transport, 'transmit', self.transmit)

    def read(self, payload):
        if self.rest_down: raise TimeoutError('OFFLINE_REST_FAILURE')
        if payload['type'] == 'orderStatus':
            return deepcopy(self.statuses.get(str(payload['oid']), {'status':'unknownOid'}))
        return self.l.fixture(payload)

    def transmit(self, payload):
        self.l.transport.check(payload['action'])
        self.auth.claim_transmission(payload['action'])
        self.l.transport.signed_payloads.append(deepcopy(payload))
        action = payload['action']; self.calls.append(deepcopy(action))
        if action['type'] == 'cancel':
            oid = str(action['cancels'][0]['o'])
            if self.cancel_uncertain: raise TimeoutError('OFFLINE_CANCEL_UNCERTAIN')
            self.l.fixture.orders = [o for o in self.l.fixture.orders if str(o['oid']) != oid]
            self.statuses[oid]['order']['status'] = 'canceled'
            return response('success', 'cancel')
        w = action['orders'][0]; self.oid += 1
        if self.fail == 'summary_without_fill' and not w['r']:
            return response({'filled':{'oid':self.oid,'totalSz':w['s'],'avgPx':w['p']}})
        if self.fail == 'entry_rejected' and not w['r']:
            return response({'error':'Order could not immediately match against any resting orders.'})
        if self.fail == 'timeout_before' and not w['r']:
            raise TimeoutError('OFFLINE_LOST_ACK')
        trigger = 'trigger' in w['t']
        if trigger and self.fail == 'protection_rejected':
            return response({'error':'Invalid TP/SL price.'})
        if trigger and self.fail == 'protection_timeout_before':
            raise TimeoutError('OFFLINE_STOP_ACK_UNKNOWN')
        qty, px = D(w['s']), D(w['p'])
        row = dict(coin='par:BTC', side='B' if w['b'] else 'A', oid=self.oid, cloid=w['c'],
                   sz=str(qty), origSz=str(qty), limitPx=str(px), isTrigger=trigger,
                   reduceOnly=w['r'], timestamp=NOW)
        if trigger:
            assert w['t']['trigger']['isMarket'] is False
            row.update(triggerPx=w['t']['trigger']['triggerPx'], orderType='Stop Limit')
            self.l.fixture.orders.append(row)
            terminal = 'open'
        else:
            held = self.l.account.get_position('par:BTC')
            fraction = self.partial_exit if w['r'] else self.partial_entry
            qty = (qty*fraction).quantize(D('.0001'))
            if not qty: return response({'error':'Order could not immediately match against any resting orders.'})
            if w['r']:
                assert held and (held.quantity > 0) != w['b']
                remaining = held.quantity+(qty if w['b'] else -qty)
                entry = held.entry_price
                pnl = qty*(px-entry)*(1 if held.quantity > 0 else -1)
            else:
                assert not held
                entry, remaining, pnl = px, qty if w['b'] else -qty, D(0)
            fee = qty*px*D('.0009')
            self.l.fixture.position(remaining, str(entry))
            self.l.fixture.fill(qty, side=row['side'], price=str(px), oid=self.oid, tid=self.oid,
                                closed=str(pnl), fee=str(fee))
            b = self.l.fixture.spot['balances'][0]
            b['total'] = str(D(b['total'])+pnl-fee)
            terminal = 'filled'; row['sz'] = '0'
        record = dict(status='order', order=dict(order=row, status=terminal, statusTimestamp=NOW))
        self.statuses[str(self.oid)] = record; self.statuses[w['c']] = record
        if trigger and self.fail == 'protection_timeout_after':
            raise TimeoutError('OFFLINE_STOP_ACCEPTED_LOST_ACK')
        if not trigger and not w['r'] and self.fail == 'timeout_after_fill':
            raise TimeoutError('OFFLINE_LOST_ACK_AFTER_FILL')
        if not trigger and not w['r'] and self.fail == 'disconnect_after_fill':
            self.rest_down = True
            raise TimeoutError('OFFLINE_DISCONNECTED_AFTER_FILL')
        return response({'resting':{'oid':self.oid}} if trigger else
                        {'filled':{'oid':self.oid, 'totalSz':str(qty), 'avgPx':str(px)}})


def test_complete_real_composition_round_trip_offline(cert):
    r = cert.sequence.run()
    assert r['status'] == 'TRADE_CLOSED_RECONCILED', r
    assert r['protection_accepted'] and r['final_flat']
    assert D(r['realized_pnl']['net_realized_pnl']) < 0
    assert not r['strategy_signal'] and not r['practice_ready']
    assert not cert.live.account.get_positions() and not cert.live.account.get_frontend_open_orders()
    assert len(cert.venue.calls) == 4
    assert cert.auth.revoked


@pytest.mark.parametrize('failure,expected', [
    ('entry_rejected','NO_FILL_VERIFIED'), ('timeout_before','EMERGENCY_EXIT_REQUIRED'),
    ('timeout_after_fill','TRADE_CLOSED_RECONCILED'), ('protection_rejected','TRADE_CLOSED_RECONCILED'),
    ('disconnect_after_fill','EMERGENCY_EXIT_REQUIRED'),
    ('protection_timeout_after','TRADE_CLOSED_RECONCILED'),
    ('protection_timeout_before','EMERGENCY_EXIT_REQUIRED'),
    ('summary_without_fill','EMERGENCY_EXIT_REQUIRED')])
def test_failure_injections(cert, failure, expected):
    cert.venue.fail = failure
    r = cert.sequence.run()
    assert r['status'] == expected, r
    entries = [a for a in cert.venue.calls if a['type'] == 'order' and not a['orders'][0]['r']]
    assert len(entries) == 1
    if expected == 'TRADE_CLOSED_RECONCILED': assert r['final_flat']
    else: assert r['realized_pnl_status'] == 'REALIZED_PNL_NOT_CERTIFIED'


def test_partial_entry_protects_actual_size(cert):
    cert.venue.partial_entry = D('.6')
    r = cert.sequence.run()
    assert r['status'] == 'TRADE_CLOSED_RECONCILED', r
    assert D(r['protection_plan']['quantity']) < D(cert.proposal.quantity)


def test_tiny_partial_is_explicit_blocker_never_enlarged(cert):
    cert.venue.partial_entry = D('.1')
    r = cert.sequence.run()
    assert r['status'] == 'EMERGENCY_EXIT_REQUIRED'
    assert cert.live.account.get_positions()
    assert len(cert.venue.calls) == 1
    assert r['realized_pnl_status'] == 'REALIZED_PNL_NOT_CERTIFIED'


def test_partial_exit_exhausts_bound_without_reversal(cert):
    cert.venue.partial_exit = D('.6')
    r = cert.sequence.run()
    assert r['status'] == 'EMERGENCY_EXIT_REQUIRED'
    assert cert.live.account.get_position('par:BTC').quantity > 0


def test_cancel_uncertain_never_claims_flat_and_reconciled(cert):
    cert.venue.cancel_uncertain = True
    r = cert.sequence.run()
    assert r['status'] == 'EMERGENCY_EXIT_REQUIRED'
    assert r['realized_pnl_status'] == 'REALIZED_PNL_NOT_CERTIFIED'
    assert cert.live.account.get_frontend_open_orders()


@pytest.mark.parametrize('field,value', [('operator_approval',''), ('manually_verified_wallets',False),
    ('sole_signer_host_confirmed',False), ('maximum_one_entry',False), ('expires_ms',NOW),
    ('expires_ms',NOW+300001), ('approved_ms',NOW+1), ('proposal_hash','wrong')])
def test_missing_or_damaged_exact_approval_blocks_all_orders(cert, field, value):
    cert.auth.approval = replace(cert.approval, **{field:value})
    r = cert.sequence.run()
    assert r['status'] == 'PREFLIGHT_BLOCKED'
    assert not cert.venue.calls and not cert.live.transport.signed_payloads


def test_source_change_blocks_certification(cert):
    cert.auth.source_hash = lambda:'changed-source'
    assert cert.sequence.run()['status'] == 'PREFLIGHT_BLOCKED'
    assert not cert.venue.calls


def test_policy_change_blocks_certification(cert):
    cert.auth.policy_hash = lambda:'changed-policy'
    assert cert.sequence.run()['status'] == 'PREFLIGHT_BLOCKED'
    assert not cert.venue.calls


def test_short_fixture_is_independent_of_strategy(cert):
    l=cert.live
    l.executor.recovery.recover()
    ctx=l.provider.load(OrderRequest('par:BTC','SELL','.2','100'))
    p=propose(ctx,l.client,'fixture-source',reliability_policy_hash='fixture-policy',side='SELL')
    a=replace(cert.approval,proposal_hash=p.identity)
    auth=CertificationAuthorization(p,a,l.journal,clock_ms=lambda:NOW,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    cert.venue.auth=auth;CertificationProtection(l.executor,p)
    r=CertificationSequence(l.executor,p,auth).run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert cert.venue.calls[0]['orders'][0]['b'] is False
    assert cert.venue.calls[1]['orders'][0]['b'] is True
    assert r['evidence_scope']=='OFFLINE_SIGNED_FIXTURE'


def test_missing_operator_approval_refuses_before_api_key(cert, tmp_path, monkeypatch):
    import hashlib
    import exchange.certification_runtime as mod
    root=tmp_path/'root';root.mkdir();(root/'configs').mkdir()
    policy=root/'configs/reliability_policy.json';policy.write_text('{}')
    proposal=replace(cert.proposal,reliability_policy_hash=hashlib.sha256(policy.read_bytes()).hexdigest())
    xml=root/'regression.xml';xml.write_text('<testsuites/>')
    receipt=root/'test_receipt.json';receipt.write_text(json.dumps(dict(passed=True,source_hash='fixture-source',
        source_hash_after='fixture-source',totals=dict(tests=1455,failures=0,errors=0,skipped=0),
        xml_sha256=hashlib.sha256(xml.read_bytes()).hexdigest(),
        checks_before=dict(strategy_freeze=dict(exit_code=0),phase0=dict(exit_code=0)))))
    monkeypatch.setattr(mod,'active_source_hash',lambda _: 'fixture-source')
    monkeypatch.setattr(mod,'read_api_key',lambda _:pytest.fail('REAL_API_KEY_LOAD_PROHIBITED'))
    with pytest.raises(ExchangeError,match='EXACT_HUMAN_CERTIFICATION_APPROVAL_REQUIRED'):
        mod.build_certification(root,proposal,None,state_directory=root/'runtime/testnet/anchorium-bot-1',
                                test_receipt=receipt)
    assert not cert.live.transport.signed_payloads


def test_final_book_refresh_keeps_account_age_and_limits(cert,monkeypatch):
    from exchange.exchange_rules import LiveContextProvider
    original=LiveContextProvider.load
    def delayed(self,req,*,critical=False):
        ctx=original(self,req,critical=critical)
        cert.live.fixture.now+=4500
        cert.live.fixture.book['time']=cert.live.fixture.now
        return ctx
    monkeypatch.setattr(LiveContextProvider,'load',delayed)
    provider=CertificationContextProvider(cert.live.market,cert.live.account,cert.live.signer.address,
        cert.live.clock,cert.live.rate,reconciliation_ready=lambda:True,feed_ready=lambda:True)
    ctx=provider.load(OrderRequest('par:BTC','BUY','.2','100'))
    assert ctx.quote.timestamp_ms==cert.live.fixture.now
    assert ctx.account_ms==NOW and cert.live.fixture.now-ctx.account_ms==4500
    assert cert.live.clock.healthy


def test_restart_after_entry_never_reenters(cert):
    cert.live.journal.control('certification_started:'+cert.proposal.identity, True)
    assert cert.sequence.run()['status'] == 'PREFLIGHT_BLOCKED'
    assert not cert.venue.calls


def test_production_live_authorization_still_locked(cert):
    with pytest.raises(Exception): LiveAuthorization().require(TEAM, cert.live.signer.address)
    with pytest.raises(ExchangeError):
        CertificationSDKTransport(cert.live.client, cert.live.signer, TEAM, cert.live.nonces,
                                  None, rate_limits=cert.live.rate)


def test_actual_activation_blocks_unverified_small_partial_path(cert):
    with pytest.raises(ExchangeError, match='SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED'):
        require_safe_partial_path(cert.live.client.market('par:BTC'), cert.proposal)
    assert not cert.live.transport.signed_payloads


def test_ephemeral_sdk_payload_has_signed_expiry_and_unique_nonce(cert):
    cert.live.transport.action_expiry_ms = cert.approval.expires_ms
    r = cert.sequence.run()
    assert r['status'] == 'TRADE_CLOSED_RECONCILED'
    assert r['evidence_scope'] == 'OFFLINE_SIGNED_FIXTURE'
    payloads = cert.live.transport.signed_payloads
    assert len({x['nonce'] for x in payloads}) == len(payloads)
    assert all(x['expiresAfter'] == cert.approval.expires_ms for x in payloads)
    assert all(x['vaultAddress'] is None for x in payloads)
    cloids = [x['action']['orders'][0]['c'] for x in payloads if x['action']['type']=='order']
    assert len(set(cloids)) == len(cloids)


def test_duplicate_transmission_rejected_after_persisted_claim(cert):
    cert.sequence.run()
    entry = cert.venue.calls[0]
    cert.auth.revoked = False
    # Keep the attempt consumed even if in-memory authorization is reconstructed.
    with cert.live.journal.transaction():
        cert.live.journal.db.execute('DELETE FROM controls WHERE name=?',
                                    ('certification_completed:'+cert.proposal.identity,))
    with pytest.raises(ExchangeError, match='CERTIFICATION_ATTEMPT_ALREADY_CONSUMED'):
        cert.auth.claim_transmission(entry)


def test_rate_budget_exhaustion_cannot_create_exposure(cert):
    cert.live.fixture.budget.update(nRequestsUsed=10000,nRequestsCap=10000)
    r=cert.sequence.run()
    assert r['status'] != 'TRADE_CLOSED_RECONCILED' and not cert.venue.calls


def test_reconciliation_mismatch_blocks_new_entry(cert):
    cert.live.fixture.position('.1')
    r=cert.sequence.run()
    assert r['status']=='PREFLIGHT_BLOCKED' and not cert.venue.calls


@pytest.mark.parametrize('damage', ['native','mainnet','oversize','budget','tif','opposite','leverage'])
def test_proposal_and_wire_cannot_expand_authorization(cert, damage):
    if damage in {'native','mainnet','oversize','budget'}:
        values = {'native':dict(symbol='BTC'), 'mainnet':dict(network='mainnet'),
                  'oversize':dict(max_notional='50'), 'budget':dict(session_loss_budget='11')}[damage]
        with pytest.raises(ExchangeError): replace(cert.proposal, **values).require()
    else:
        action = {'type':'updateLeverage'} if damage == 'leverage' else dict(type='order', orders=[
            dict(a=cert.proposal.asset_id,b=damage!='opposite',r=False,s=cert.proposal.quantity,
                 p=cert.proposal.entry_limit,t={'limit':{'tif':'Gtc' if damage=='tif' else 'Ioc'}},c='0x'+'0'*32)])
        with pytest.raises(ExchangeError): cert.auth.check_action(action)


@pytest.mark.parametrize('damage', ['stale','spread','oracle','margin','depth','held','not_cross'])
def test_book_account_and_liquidity_gates(cert, damage):
    l = cert.live
    c = l.provider.load(OrderRequest('par:BTC','BUY','.2','100'))
    if damage == 'stale': c = replace(c, quote=replace(c.quote,timestamp_ms=NOW-5001))
    if damage == 'spread': c = replace(c, quote=replace(c.quote,ask=D(101),mid=D('100.495')))
    if damage == 'oracle': c = replace(c, quote=replace(c.quote,oracle=D(105)))
    if damage == 'margin': c = replace(c,active_asset=dict(c.active_asset,availableToTrade=['1','1']))
    if damage == 'depth': c = replace(c, quote=replace(c.quote,ask_quantity=D('.1')))
    if damage == 'held': c = replace(c, positions={'par:ETH':object()})
    if damage == 'not_cross': c = replace(c,active_asset=dict(c.active_asset,leverage=dict(type='isolated',value=1)))
    with pytest.raises(ExchangeError): propose(c,l.client,'fixture-source', reliability_policy_hash='fixture-policy')


@pytest.mark.parametrize('damage', ['closed','fee','quantity','source','duplicate'])
def test_accounting_rejects_mismatched_or_invented_events(cert,damage):
    r = cert.sequence.run(); assert r['status']=='TRADE_CLOSED_RECONCILED'
    fills = list(cert.live.executor.recovery.state.fills.values())
    entry, exit = sorted(fills,key=lambda f:int(f.trade_id))
    if damage=='closed': exit=replace(exit,closed_pnl=D(99))
    if damage=='fee': exit=replace(exit,fee=D(1))
    if damage=='quantity': exit=replace(exit,quantity=exit.quantity/2)
    if damage=='source': entry=replace(entry,source='PAPER')
    entries=[entry,entry] if damage=='duplicate' else [entry]
    with pytest.raises(ExchangeError): certify_realized(entries,[exit],[],cert.proposal)
