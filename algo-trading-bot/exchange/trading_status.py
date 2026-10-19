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
    return dict(authorization_status='TRADING_AUTHORIZED' if status=='TRADING_ACTIVE' else status,
        trading_status=status,entry_markets=list(limits.markets),authorization_valid=valid,
        renewal_permitted=False)
