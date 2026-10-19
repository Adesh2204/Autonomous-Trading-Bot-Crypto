"""Report-only refresh from retained public receipts. No network or signer."""
from pathlib import Path
from decimal import Decimal as D
import json,time,sys
R=Path(__file__).resolve().parents[2];P=Path(__file__).resolve().parent
sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.pas_funding import current_funding
read=lambda p:json.loads((P/p).read_text())
write=lambda p,v:(P/p).write_text(json.dumps(v,indent=2)+'\n')
d=read('discovery_final/discovery.json');f=read('final_market_read/snapshot.json')
c=json.loads((R/'runtime/pas-btc-ewy-v4/current.json').read_text());live=json.loads((Path(c['output'])/'status.json').read_text());now=time.time_ns()//1000000
v=dict(observed_ms=f['observed_ms'],source_hash=f['source_hash'],configured_team='0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C',old_screenshot_address='0xe590711084f687d278516f4882c075a862cd73cb',old_address_evidence='docs/team_account_setup_2026-10-06/read_only_state.json',operator_reply='Yes this is same from Local Records',operator_reply_interpretation='Does not distinguish both wallets or provide original organizer registration provenance; configured identity unchanged',organizer_registered_wallet=None,registered_wallet_status='UNKNOWN_ORIGINAL_ORGANIZER_WALLET_BINDING_REQUIRED',official_lookup='docs/btc_ewy_v4_2026-10-19/official_sources/registration_lookup.json',mode=f['account_mode'],funding=current_funding(live.get('funding'),now),approved_agents=f['agents'],fees=f['fees'],account=live['account'],account_observed_ms=live['account_observed_ms'],discovery_account=d['account'],two_flat_readbacks=f['flat_readbacks'],terminal_flat=f['terminal_flat'],selected_configuration_plan=d['configuration_plan'],configuration_proposal_age_ms=now-d['finished_ms'],configuration_authorized=False)
write('account_report.json',v)
f=read('original_order_audit/readback.json');old=json.loads((R/'docs/activation_v3_2026-10-19/historical_disposition.json').read_text())
write('historical_recovery.json',dict(observed_ms=f['observed_ms'],source_hash=f['source_hash'],verdict='BLOCKED_EXTERNAL_ORDER_EVIDENCE',original_cloid=f['cloid'],original_nonce=f['nonce'],original_dex='par',current_readbacks=f['readbacks'],prior_forensic_review='docs/activation_v3_2026-10-19/historical_disposition.json',original_row=old['original_row'],prior_certificate_different_cloid=old['prior_certificate_different_cloid'],prior_certificate_reused=False,nonce_reset=False,records_modified=False,safe_isolation_approved=False,consumed_attempt_reset=False,consumed_attempt_disposition='TERMINAL_DO_NOT_RESTART; independent review required',reason='unknownOid and current flatness do not establish original rejection, nontransmission or terminal outcome. Shared team/API/nonce hazards remain; no isolation approved.'))
h=read('history_review_release/history_review.json');v={}
for s,r in h['markets'].items():
 rows=r.get('funding_history',[]);rates=[D(x['fundingRate']) for x in rows];premiums=[D(x['premium']) for x in rows]
 v[s]=dict(source_hash=h['source_hash'],observed_ms=h['observed_ms'],funding_samples=len(rows),first_sample_ms=min(x['time'] for x in rows) if rows else None,last_sample_ms=max(x['time'] for x in rows) if rows else None,minimum_hourly_rate=str(min(rates)) if rates else None,maximum_hourly_rate=str(max(rates)) if rates else None,minimum_reported_premium=str(min(premiums)) if rows else None,maximum_reported_premium=str(max(premiums)) if rows else None,premium_is_mark_oracle_divergence=False,current_context=r['asset_context'],adverse_one_hour_cost_per_1000_oracle_notional=str(max([D(0),*rates])*1000),interpretation='Historical positive rates can make LONG funding expensive. A current negative rate cannot assure future credits or profitable execution. Reported premium is not substituted for directly observed mark/oracle divergence.',production_six_times_fee_stress_changed=False,expected_net_profit=None,authorizes_trade=False,evidence='history_review_release/info_receipts.jsonl')
write('funding_distortion_review.json',v)
print(json.dumps(dict(source=h['source_hash'],account_observed_ms=live['account_observed_ms'],funding=v['pas:EWY']['maximum_hourly_rate'],historical='BLOCKED_EXTERNAL_ORDER_EVIDENCE')))
