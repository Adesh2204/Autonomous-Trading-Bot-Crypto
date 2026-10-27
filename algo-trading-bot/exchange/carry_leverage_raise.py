"""Raise the five carry markets from 1x to 2x CROSS while the carry basket is open. Configuration only.

User directive 27 Oct 2026 09:05 IST: keep HYPE exactly as held, move to a 2x setting with 1.5x exposure,
and change the rule that leverage is configured only on a flat, order-free account (answered question:
"Yes, change the rule"). The general PAS configuration route keeps that rule. This route only RAISES the
cross setting of the carry markets from 1 to 2. A higher cross setting lowers the initial margin the open
positions hold; it places, cancels or changes no order or position. Anything else is refused.

Allowed open state, read fresh for the plan and again before every signature, and equal to what the
human approved:
  * positions only in carry markets, each on the basket's side;
  * resting orders only full-size reduce-only trigger stops, at most one per held market, each journaled
    as that market's OPEN protection intent (and every OPEN protection intent resting);
  * local journals: a carry child row not terminal locally must be terminal on the exchange; the only
    UNKNOWN allowed is the historical qualification row while the exchange reports it unknownOid;
  * no par-dex position or order; funded unified account; healthy clock, nonce and rate budget.
Signing reuses the configuration transport: exact single-use action permits, the typed approval phrase
bound to the plan hash, one durable attempt per plan, no retry after ambiguity, and an exchange readback.
"""
from pathlib import Path
import json, socket, time

from .base_exchange import ExchangeError, decimal
from .execution_journal import fingerprint
from .testnet_certification import TEAM, API

TARGET = 2
CHILD_PREFIXES = ('carry-in', 'carry-trim', 'carry-out', 'carry-exit')
PLAN_MAX_AGE_MS = 300000


def _terminal_on_exchange(account, cloid):
    status = account._query('orderStatus', oid=cloid)
    order = status.get('order') if isinstance(status, dict) and status.get('status') == 'order' else None
    state = order.get('status') if isinstance(order, dict) else None
    return isinstance(state, str) and (state in {'filled', 'canceled', 'rejected'}
                                       or state.endswith('Canceled') or state.endswith('Rejected'))


def basket_evidence(root, client, account, *, owned_actions=()):
    """The open carry basket, proven to hold nothing but basket positions and their own stops.

    `owned_actions`: this route's own management row, journaled UNKNOWN just before it signs (the
    same exemption require_shared_scope gives the configuration route's current action)."""
    from .carry_runtime import CARRY_BASKET
    from .configuration_isolation import CLOID, INTENT
    from .scored_session import require_no_par_exposure
    from .terminal_evidence import local_execution_state
    basket = dict(CARRY_BASKET)
    positions = {s: p for s, p in account.get_positions().items() if p.quantity}
    if any(s not in basket or (p.quantity > 0) != (basket[s] == 'LONG') for s, p in positions.items()):
        raise ExchangeError('CARRY_BASKET_POSITIONS_ONLY')
    local = local_execution_state(root)
    if local['status'] not in {'NO_LOCAL_UNRESOLVED_INTENT', 'BLOCKED_UNRESOLVED_INTENT'}:
        raise ExchangeError('LOCAL_JOURNAL_STATE_REQUIRED')
    stops, settled = {}, []
    for row in local['unresolved']:
        key = row.get('intent_key') or ''
        if (row.get('journal') == 'qualification' and row.get('cloid') == CLOID and key == INTENT
                and row.get('state') == 'UNKNOWN'):
            if account._query('orderStatus', oid=CLOID) != {'status': 'unknownOid'}:
                raise ExchangeError('HISTORICAL_UNKNOWN_REQUIRES_REVIEW')
            continue
        if (row.get('journal') == 'pas-configuration' and row.get('management_id') in set(owned_actions)
                and row.get('state') == 'UNKNOWN'):
            continue
        parts = key.split(':')
        symbol = ':'.join(parts[1:3]) if len(parts) >= 3 else None
        if row.get('journal') != 'pas' or row.get('state') == 'UNKNOWN' or symbol not in basket:
            raise ExchangeError('UNRESOLVED_LOCAL_ACTION_BLOCKS_CONFIGURATION')
        if parts[0] == 'protection' and row['state'] == 'OPEN':
            stops[row['cloid']] = symbol
        elif parts[0] in CHILD_PREFIXES and _terminal_on_exchange(account, row['cloid']):
            settled.append(key)
        else:
            raise ExchangeError('UNRESOLVED_LOCAL_ACTION_BLOCKS_CONFIGURATION')
    orders = account.get_frontend_open_orders()
    covered = set()
    for o in orders:
        coin, position = o.get('coin'), positions.get(o.get('coin'))
        if (o.get('isTrigger') is not True or o.get('reduceOnly') is not True or position is None
                or stops.get(o.get('cloid')) != coin or coin in covered
                or decimal(o.get('sz'), positive=True) != abs(position.quantity)
                or o.get('side') != ('A' if position.quantity > 0 else 'B')):
            raise ExchangeError('ONLY_FULL_SIZE_REDUCE_ONLY_BASKET_STOPS_MAY_REST')
        covered.add(coin)
    if set(stops) != {o.get('cloid') for o in orders} or len(account.get_open_orders()) != len(orders):
        raise ExchangeError('JOURNAL_AND_EXCHANGE_ORDERS_DISAGREE')
    require_no_par_exposure(client)
    return dict(positions={s: str(p.quantity) for s, p in sorted(positions.items())},
                stops=sorted([o['coin'], o.get('cloid'), o.get('sz'), o.get('triggerPx')] for o in orders),
                settled_local_rows=sorted(settled))


def read_only_client(output):
    """Rate-limited, receipted public client for the plan (the same construction as venue discovery)."""
    from .execution_journal import ExecutionJournal
    from .execution_safety import HyperliquidRateLimitManager
    from .hyperliquid_client import RequestsInfoTransport
    from .public_quant_operator import SerializedPublicClient, ReadOnlyReceipts
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    journal = ExecutionJournal(output / 'public.sqlite', session_id='public:pas:carry-leverage-plan', team_address=TEAM)
    rates = HyperliquidRateLimitManager(journal)
    rates.read_budget_wait_seconds = 65
    rates.read_deadline_seconds = 75
    client = SerializedPublicClient(ReadOnlyReceipts(RequestsInfoTransport(), output / 'info_receipts.jsonl'),
                                    rate_limits=rates, venue='pas')
    client.startup()
    return client, journal


def raise_plan(root, client, account, *, provenance):
    """Unsigned plan: every carry market at 1x CROSS becomes 2x CROSS. Never an action permit."""
    from .entry_scope import CARRY_ENTRY_MARKETS, CARRY_2X_SCOPE
    from .paper_operations import active_source_hash
    from .pas_funding import read_funding
    source = active_source_hash(root)
    funding = read_funding(client, account, provenance=provenance)
    if funding['status'] != 'USDP_POSITIVE_VERIFIED' or funding['account_mode'] != 'unifiedAccount':
        raise ExchangeError('FRESH_PAS_UNIFIED_FUNDING_REQUIRED')
    evidence = basket_evidence(root, client, account)
    changes, already = [], []
    for symbol in sorted(CARRY_ENTRY_MARKETS):
        spec = client.market(symbol)
        current = account._query('activeAssetData', coin=symbol)
        if (not isinstance(current, dict) or current.get('coin') != symbol
                or str(current.get('user', '')).lower() != TEAM.lower()):
            raise ExchangeError('INVALID_ACTIVE_ASSET_CONFIGURATION')
        if spec.max_leverage < TARGET:
            raise ExchangeError('TARGET_LEVERAGE_ABOVE_MARKET_MAXIMUM')
        before = current.get('leverage')
        if before == dict(type='cross', value=TARGET):
            already.append(symbol)
        elif before == dict(type='cross', value=1):
            changes.append(dict(symbol=symbol, observed_ms=client.clock_ms(), before=before,
                                requested_action=dict(type='updateLeverage', asset=spec.asset_id, isCross=True,
                                                      leverage=TARGET)))
        else:
            raise ExchangeError('ONLY_A_RAISE_FROM_1X_CROSS')
    if active_source_hash(root) != source:
        raise ExchangeError('SOURCE_CHANGED_DURING_PLAN')
    plan = dict(status='UNSIGNED_CARRY_LEVERAGE_RAISE_PLAN', network='testnet', dex='pas', collateral='USDP',
                team_wallet=TEAM, source_hash=source, observed_ms=client.clock_ms(),
                configuration_scope=CARRY_2X_SCOPE, target_leverage=TARGET,
                entry_markets=sorted(CARRY_ENTRY_MARKETS), changes=changes, already_two_x_cross=sorted(already),
                open_basket=evidence, collateral_balance=funding['balance'],
                orders_permitted=False, transfers_allowed=False, account_mode_change=False,
                basis='User directive 27 Oct 2026 09:05 IST: raise the carry markets to a 2x cross setting while '
                      'the basket is open (raise only; HYPE held as is; exposure capped at 1.5x by the mandate).')
    plan['plan_hash'] = fingerprint(plan)
    return plan


def require_plan(root, plan, now):
    from .paper_operations import active_source_hash
    check = dict(plan)
    identity = check.pop('plan_hash', None)
    if (identity != fingerprint(check) or plan.get('status') != 'UNSIGNED_CARRY_LEVERAGE_RAISE_PLAN'
            or plan.get('target_leverage') != TARGET or plan.get('source_hash') != active_source_hash(root)
            or type(plan.get('observed_ms')) is not int or not 0 <= now - plan['observed_ms'] <= PLAN_MAX_AGE_MS):
        raise ExchangeError('FRESH_EXACT_CARRY_LEVERAGE_PLAN_REQUIRED')
    if not plan['changes']:
        raise ExchangeError('NO_CONFIGURATION_ACTION_REQUIRED')
    return plan


def approve_raise(root, plan_path, release, output):
    """Real terminal input is the only acceptance writer."""
    import sys
    from dataclasses import asdict
    from .long_session import require_release, sha
    from .pas_configuration import PasConfigurationApproval
    plan = json.loads(Path(plan_path).read_text())
    require_plan(root, plan, time.time_ns() // 1000000)
    require_release(root, release, plan['source_hash'], sha(release))
    if not sys.stdin.isatty():
        raise ExchangeError('GENUINE_INTERACTIVE_CONFIGURATION_APPROVAL_REQUIRED')
    print(json.dumps(plan, indent=2))
    print('Confirm: raise the listed carry markets to 2x CROSS only, with the open basket shown above. '
          'No order, cancellation, transfer or account-mode change.')
    phrase = 'APPROVE PAS CONFIGURATION ' + plan['plan_hash']
    if input(phrase + '\n> ').strip() != phrase:
        raise ExchangeError('CONFIGURATION_APPROVAL_NOT_ACCEPTED')
    accepted = time.time_ns() // 1000000
    require_plan(root, plan, accepted)
    a = PasConfigurationApproval(plan['plan_hash'], plan['source_hash'], sha(release), accepted, accepted + 900000,
                                 socket.gethostname(), phrase, True, True)
    a.require(TEAM, API, accepted)
    with Path(output).open('x') as f:
        f.write(json.dumps(asdict(a), indent=2) + '\n')
    return dict(status='EXACT_CONFIGURATION_APPROVAL_ACCEPTED', expires_ms=a.expires_ms, plan_hash=a.plan_hash)


def execute_raise(root, plan_path, release, acceptance, output):
    """One durable attempt per approved plan; ambiguity consumes it. Public checks precede key access."""
    from .long_session import sha, require_release
    from .leverage_configuration import LeverageConfigurationTransport, wait_for_configuration_reads
    from .execution_journal import ExecutionJournal
    from .execution_safety import NonceManager, ClockHealthMonitor, HyperliquidRateLimitManager
    from .public_quant_operator import SerializedPublicClient, ReadOnlyReceipts
    from .hyperliquid_client import RequestsInfoTransport
    from .hyperliquid_market_data import HyperliquidMarketData
    from .hyperliquid_account import HyperliquidAccount
    from .live_readiness import verify_live_account_readiness
    from .reliability_policy import load_reliability_policy
    from .order_lifecycle import parse_exchange_action_result, OrderState
    from .paper_operations import PaperOwner, active_source_hash, atomic_json
    from .pas_configuration import PasConfigurationApproval
    from venue_config import require_paper_migration
    from strategy_freeze import verify_strategy_freeze
    root, out = Path(root), Path(output)
    out.mkdir(parents=True, exist_ok=False)
    p = json.loads(Path(plan_path).read_text())
    a = PasConfigurationApproval(**json.loads(Path(acceptance).read_text()))
    now = time.time_ns() // 1000000
    a.require(TEAM, API, now)
    require_plan(root, p, a.approved_ms)            # fresh at the genuine approval; every check repeats below
    if a.plan_hash != p['plan_hash'] or a.source_hash != active_source_hash(root) or sha(release) != a.release_sha256:
        raise ExchangeError('CONFIGURATION_APPROVAL_SOURCE_OR_PLAN_CHANGED')
    require_release(root, release, a.source_hash, a.release_sha256)
    require_paper_migration('pas')
    verify_strategy_freeze()
    state = root / 'runtime/testnet/anchorium-bot-1'
    owner = PaperOwner(state / 'pas-configuration-owner.lock')
    journal = client = transport = nonces = None
    result = dict(status='CONFIGURATION_CHECKING', orders_submitted=0, configuration_actions_submitted=0, results=[])
    try:
        journal = ExecutionJournal(state / 'pas-configuration.sqlite', session_id='pas-config:' + a.plan_hash,
                                   team_address=TEAM)
        rate, clock_policy, _ = load_reliability_policy(root / 'configs/reliability_policy.json')
        rates = HyperliquidRateLimitManager(journal, policy=rate, signer_address=API)
        rates.read_budget_wait_seconds = 65
        rates.read_deadline_seconds = 75
        client = SerializedPublicClient(ReadOnlyReceipts(RequestsInfoTransport(), out / 'info_receipts.jsonl'),
                                        rate_limits=rates, venue='pas')
        client.startup()
        account, market = HyperliquidAccount(client, TEAM), HyperliquidMarketData(client)
        clock = ClockHealthMonitor(clock_ms=client.clock_ms, journal=journal, **clock_policy)
        acceptance_hash = sha(acceptance)
        current_action = [None]

        def guard():
            require_paper_migration('pas')
            a.require(TEAM, API, client.clock_ms())
            if active_source_hash(root) != a.source_hash or sha(acceptance) != acceptance_hash:
                raise ExchangeError('CONFIGURATION_SOURCE_OR_ACCEPTANCE_CHANGED')
            require_release(root, release, a.source_hash, a.release_sha256)
            wait_for_configuration_reads(rates, a, TEAM, API, venue='pas')
            client.startup()
            evidence = basket_evidence(root, client, account,
                                       owned_actions=tuple(x for x in current_action if x is not None))
            if (evidence['positions'] != p['open_basket']['positions']
                    or evidence['stops'] != p['open_basket']['stops']):
                raise ExchangeError('OPEN_BASKET_CHANGED_SINCE_APPROVAL')
            for _ in range(3):
                sent = client.clock_ms()
                book = market.get_orderbook('pas:BTC')
                clock.observe(book.timestamp_ms, sent, client.clock_ms())
                if clock.healthy:
                    break
                rates.wait(250)
            ready = verify_live_account_readiness(account, API, clock_health=clock, rate_limits=rates,
                                                  reconciliation_ready=True)
            if not ready.account_ready or nonces is not None and not nonces.healthy:
                raise ExchangeError('CONFIGURATION_ACCOUNT_CLOCK_NONCE_HEALTH_REQUIRED')
            for row in p['changes']:
                if client.market(row['symbol']).asset_id != row['requested_action']['asset']:
                    raise ExchangeError('CONFIGURATION_RUNTIME_MAPPING_CHANGED')
        guard()
        key = 'pas_configuration_attempt:' + a.plan_hash
        with journal.transaction():
            if journal.db.execute('select 1 from controls where name=?', (key,)).fetchone():
                raise ExchangeError('CONFIGURATION_RESTART_REVIEW_REQUIRED')
            journal.db.execute('insert into controls values(?,?)', (key, 'CONSUMED'))
        from .practice_preflight import read_api_key, api_signer
        secret, _ = read_api_key(root)
        try:
            signer = api_signer(secret, API, TEAM)
        finally:
            secret = None
        nonces = NonceManager(state / 'nonces.sqlite', API, journal=journal)
        transport = LeverageConfigurationTransport(client, signer, TEAM, nonces, a, rates=rates,
                                                   readiness_guard=guard, approved_plan=p)
        for row in p['changes']:
            guard()
            symbol, action = row['symbol'], row['requested_action']
            if journal.pending_management(action):
                raise ExchangeError('CONFIGURATION_UNCERTAIN_ACTION_NO_RETRY')
            current = account._query('activeAssetData', coin=symbol)
            if current.get('leverage') == dict(type='cross', value=TARGET):
                continue
            if current.get('leverage') != row['before']:
                raise ExchangeError('CONFIGURATION_BEFORE_VALUE_CHANGED')
            action_id = journal.reserve_management(action, client.clock_ms())
            before = transport.transmission_attempts
            current_action[0] = action_id
            try:
                rates.reserve_action(kind='updateLeverage')
                response = transport.set_target_cross(symbol)
                result['configuration_actions_submitted'] += transport.transmission_attempts - before
                outcome = parse_exchange_action_result(response, [None], action='updateLeverage')[0]
                if outcome.code == 'NONCE_ERROR':
                    nonces.degrade()
                if outcome.state != OrderState.ACKNOWLEDGED:
                    raise ExchangeError('CONFIGURATION_NOT_ACKNOWLEDGED')
                current = account._query('activeAssetData', coin=symbol)
                if (current.get('user', '').lower() != TEAM.lower() or current.get('coin') != symbol
                        or current.get('leverage') != dict(type='cross', value=TARGET)):
                    raise ExchangeError('AUTHORITATIVE_TWO_X_READBACK_REQUIRED')
                journal.update_management(action_id, 'ACKNOWLEDGED', client.clock_ms())
                result['results'].append(dict(symbol=symbol, response=response, readback=current,
                                              observed_ms=client.clock_ms()))
                atomic_json(out / 'result.json', result)
            except Exception:
                if transport.transmission_attempts == before:
                    journal.update_management(action_id, 'REJECTED_BEFORE_TRANSMISSION', client.clock_ms())
                raise
            finally:
                current_action[0] = None
        for s in p['entry_markets']:
            r = account._query('activeAssetData', coin=s)
            if (r.get('coin') != s or r.get('user', '').lower() != TEAM.lower()
                    or r.get('leverage') != dict(type='cross', value=TARGET)):
                raise ExchangeError('SELECTED_MARKETS_TWO_X_READBACKS_REQUIRED')
        final = basket_evidence(root, client, account)
        if final['positions'] != p['open_basket']['positions'] or final['stops'] != p['open_basket']['stops']:
            raise ExchangeError('OPEN_BASKET_CHANGED_DURING_CONFIGURATION')
        result.update(status='SELECTED_MARKETS_TWO_X_CROSS_VERIFIED', verified_markets=p['entry_markets'],
                      verified_ms=client.clock_ms(), target_leverage=TARGET, open_basket_after=final)
    except Exception as exc:
        result.update(status='CONFIGURATION_REQUIRES_REVIEW', error=str(exc), blind_retry=False)
    finally:
        if transport:
            result['configuration_actions_submitted'] = transport.transmission_attempts
            transport.close()
        if nonces:
            nonces.close()
        if client:
            client.close()
        if journal:
            journal.close()
        owner.close()
        atomic_json(out / 'result.json', result)
    return result
