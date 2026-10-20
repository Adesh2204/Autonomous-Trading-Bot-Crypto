"""Status derived from the running finite capability, never a public JSON flag."""
def authorized_status(runtime,now_ms,stopping=False):
    auth=runtime.authorization;limits=auth.m.daily
    try:
        auth.require(limits.team_wallet,limits.api_wallet)
        valid=True
    except Exception:
        valid=False
    expired=now_ms>=limits.expires_ms
    state=runtime.session.execution.daily.state.value
    failed=state in {'UNKNOWN','HALTED','UNPROTECTED_EXPOSURE','RECOVERY_REQUIRED','REJECTED'}
    streams=bool(getattr(runtime,'market_stream',None) and runtime.market_stream.connected and runtime.market_stream.reconciled
        and getattr(runtime.session,'account_stream',None) and runtime.session.account_stream.healthy)
    status=('TRADING_EXPIRED' if expired else 'TRADING_BLOCKED' if not valid else
        'TRADING_PAUSED' if stopping or failed or not streams or runtime.session.execution.entries_paused else 'TRADING_ACTIVE')
    # A running scanner/capability alone is not actual exchange activity. Match
    # an owned, transmitted original order to authoritative account evidence.
    data=getattr(auth,'data',{})
    sent={r.get('key') for r in data.get('transmissions',[]) if r.get('kind') in {'entry','exit','protection'}}
    owned=set(data.get('owned',{})) & sent
    journal=getattr(runtime,'journal',None)
    oids={str(r['oid']) for r in journal.intents() if r.get('intent_key') in owned and r.get('oid') is not None} if journal else set()
    truth=getattr(getattr(runtime.session,'recovery',None),'state',None)
    fills=getattr(truth,'fills',{})
    confirmed=any(str(f.order_id) in oids and f.symbol in limits.markets
        and getattr(limits,'starts_ms',now_ms)<=f.timestamp_ms<=now_ms for f in fills.values())
    return dict(authorization_status='TRADING_AUTHORIZED' if status=='TRADING_ACTIVE' else status,
        trading_status=status,entry_markets=list(limits.markets),authorization_valid=valid,
        TRADING_AUTHORIZED=status=='TRADING_ACTIVE',AUTO_TRADING_ACTIVE=status=='TRADING_ACTIVE' and confirmed,
        exchange_activity_confirmed=confirmed,
        renewal_permitted=False)
