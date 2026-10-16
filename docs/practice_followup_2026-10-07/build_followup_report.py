"""Build a plain-language result only after real readback and saved checks."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration


def read(p):
    return json.loads(Path(p).read_text())


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def link(name,label):
    return f'[{label}](<{(OUT/name).resolve()}>)'


source=active_source_hash(ROOT)
tests=read(OUT/'test_receipt.json')
applied=read(OUT/'leverage_applied_paced.json')
account=read(OUT/'account_check_after.json')
signer=read(OUT/'signer_preflight_after.json')
paper=read(OUT/'paper_completion_corrected.json')
post=read(OUT/'post_configuration_paper_receipt.json')
post_health=post['final_health']
post_segment=Path(post_health['segment'])
post_report=read(post_segment/'report.json')
post_funnel=read(post_segment/'results/funnel_summary.json')
post_scanner=next(s for s in post_funnel['session']['stages'] if s['stage']=='SCANNER_QUALIFIED')
post_rows=[json.loads(s) for s in (OUT/'post_configuration_health_samples.jsonl').read_text().splitlines()]
post_running=list({s['timestamp_ms']:s for s in post_rows if s.get('status')=='RUNNING' and s.get('segment')==str(post_segment)}.values())
settings={s:v.get('leverage') for s,v in account['active_asset_data'].items()}
aligned=(applied['status']=='ALL_TEN_ONE_X_CROSS_VERIFIED' and len(settings)==10 and all(v==dict(type='cross',value=1) for v in settings.values()))
freeze=verify_strategy_freeze()
safety=require_paper_migration()
policy=read(ROOT/'configs/reliability_policy.json')
assert source==tests['source_hash_before']==tests['source_hash_after']==account['active_source_hash']==applied['active_source_hash']
assert tests['exit_code']==0 and tests['totals']['failures']==tests['totals']['errors']==0
assert signer['status']=='LOCAL_IDENTITY_AND_OWNERSHIP_VERIFIED' and signer['active_source_hash']==source
assert freeze['passed'] and aligned
assert account['account_ready_read_only'] and account['api_agent_ready_read_only'] and account['reconciliation_ready_read_only']
assert policy['protection']['enabled'] is False
assert applied['orders_submitted']==0 and post['exchange_orders_submitted']==0
assert post['source_hash_before']==post['source_hash_after']==source and post['source_unchanged']
assert post['exit_code']==0 and post_health['status']=='STOPPED'
checks=read(OUT/'operating_checks_after.json')
assert checks['paper_owner_lease_released'] and checks['checkpoint_integrity_ok']
now=datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Calcutta')).isoformat()
flags=dict(STRATEGY_FREEZE='PASS',FULL_TEST_SUITE='PASS',HUMAN_WALLET_IDENTITIES_VERIFIED='YES',
    ACCOUNT_READY_READ_ONLY='YES' if account.get('account_ready_read_only') else 'NO',
    API_AGENT_READY_READ_ONLY='YES' if account.get('api_agent_ready_read_only') else 'NO',
    READ_ONLY_RECONCILIATION_READY='YES' if account.get('reconciliation_ready_read_only') else 'NO',
    API_SIGNER_IDENTITY_VERIFIED='YES',NONCE_LOCAL_HEALTHY='YES',REMOTE_SIGNER_OWNERSHIP_VERIFIED='NO',
    LEVERAGE_ALIGNED='YES',PROTECTION_CONFIGURED='YES',PROTECTION_ENABLED='NO',
    PAPER_OPERATION_VERIFIED='YES',SUSTAINED_USABLE_SIGNAL_FEED_DEMONSTRATED='NO',
    LONG_CERTIFIED='NO',SHORT_CERTIFIED='NO',FUNDED_RECOVERY_CERTIFIED='NO',PRACTICE_READY='NO',LIVE_READY='NO')
paths=['test_receipt.json','regression.xml','configuration_tests_corrected.xml','configuration_integration_receipt.json',
    'leverage_applied.json','leverage_applied_paced.json','account_check_after.json','signer_preflight_after.json','paper_completion_corrected.json',
    'followup_paper_receipt.json','followup_health_samples.jsonl','post_configuration_paper_receipt.json',
    'post_configuration_health_samples.jsonl','operating_checks_after.json','next_steps.md']
result=dict(created_at_ist=now,scope='AUTHORIZED_LEVERAGE_CONFIGURATION_AND_LOCKED_PAPER_FOLLOWUP',
    safety=safety,strategy_freeze=freeze,tests=tests['totals'],active_source_hash=source,
    paper_prior_source_hash=paper['source_hash'],paper_prior_source_same_as_current=False,
    source_change_explanation='Only configuration pacing/clock refresh/diagnostics and its offline regression test changed after the 15-minute run. Preserve that run and ledger under their original fingerprint.',
    manual_wallet_verified=True,signer_preflight=signer,configuration_actions_submitted=applied['configuration_actions_submitted'],
    actual_orders_submitted=0,all_ten_settings=settings,account_observation_ist=account['observed_at_ist'],
    account_read_only=account['account_verification'],reported_equity=account['reported_equity'],
    account_positions=len(account['positions']),ordinary_orders=len(account['open_orders']),trigger_aware_orders=len(account['frontend_open_orders']),
    policy=policy['protection'],completed_followup_paper=paper,
    completed_post_configuration_paper=dict(elapsed_seconds=post['finished_unix']-post['started_unix'],
      scanner_qualified=post_scanner['passed'],scanner_rejections=post_scanner['rejection_reasons'],
      heartbeats=len(post_running),any_healthy_samples=sum(bool(s['data_healthy']) for s in post_running),
      healthy_counts=dict(Counter(m for s in post_running for m in s['healthy_markets'])),
      local_fills=post_health['local_fills'],reconnections=post_health['public_stream']['reconnections'],
      source_unchanged=post['source_unchanged'],segment=str(post_segment)),
    readiness=flags,operating_checks=checks,evidence_sha256={p:digest(OUT/p) for p in paths},
    research_flags={k:False for k in ['SESSION_ANCHOR_VALIDATED','ML_DATA_READY','ML_MODEL_VALIDATED','HOLDOUT_COMPLETE','PROMOTION_RECOMMENDED','PRODUCTION_CHANGED']},
    research_flags_scope='Research validation/promotion only; infrastructure was changed.',
    git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    working_tree_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()))
for name in ['readiness.json','report.md']:
    if (OUT/name).exists():raise RuntimeError('PRESERVE_EXISTING_FINAL_REPORT')
(OUT/'readiness.json').write_text(json.dumps(result,indent=2,default=str)+'\n')
rows='\n'.join(f'| `{s}` | {v["value"]}x CROSS |' for s,v in sorted(settings.items()))
flag_rows='\n'.join(f'| `{k}` | **{v}** |' for k,v in flags.items())
prior_reasons=', '.join(f'{k}: {v}' for k,v in paper['scanner_rejection_reasons_this_segment'].items())
post_reasons=', '.join(f'{k}: {v}' for k,v in post_scanner['rejection_reasons'].items())
report=f'''# Team Anchorium: completed 1x CROSS configuration and PAPER follow-up

Created: {now}.

**All ten competition markets are now verified at 1x CROSS on the actual testnet account. The configuration helper is fixed and all 1,278 repository tests pass. Orders remain locked, and funded trading practice is still not certified.**

## 1. What was completed

You manually verified the registered team wallet and approved API wallet. The separately authorized helper then changed exactly the ten `par:` leverage settings. It used the official SDK, runtime asset IDs, durable nonce/account ownership and exact-action checks. Each setting was read back from the exchange, then checked again in a separate read-only account audit. It submitted **{applied['configuration_actions_submitted']} leverage configuration actions** and **zero trading orders**. It made no transfer, cancellation or account-mode change.

The first apply attempt stopped safely before any HTTP submission. The full helper flow reproduced this problem offline: its repeated fresh-account checks consumed the local request-weight allowance before the first configuration action. The fix waits for read capacity, preserves the safety reserve, checks approval expiry throughout the wait and repeats the complete account check afterward. A wait can age the previous clock reference, so the helper collects the existing required distinct fresh references before continuing. It does not weaken clock limits or retry an uncertain signed action.

Failures now save reason codes plus clock/rate observations instead of only a generic message. The first failed attempt and intermediate development test results remain saved. The final targeted suite passed 29 tests; the full suite passed **{tests['totals']['tests']} tests with zero failures, errors or skips**. Its ten-market integration uses an ephemeral signer and fake HTTP, and is clearly labeled offline. The actual setting change has separate real exchange evidence.

Evidence: {link('leverage_applied_paced.json','actual configuration and ten-market readback')}, {link('configuration_integration_receipt.json','offline full-helper integration')}, {link('test_receipt.json','full test and freeze receipt')}.

## 2. Actual wallet and exchange settings

Read-only account observation: **{account['observed_at_ist']}**.

| Check | Observed result |
| --- | --- |
| Network / DEX | Hyperliquid testnet / `par` |
| Registered team wallet | `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` |
| Approved API wallet | `0x46c9BED595770150752E7fA3806449F81E0Ec6f9` |
| USDPR collateral / reported account value | {account['reported_equity']['collateral_balance']} / {account['reported_equity']['reported_account_value']} |
| Account mode | `{account['account_mode']}` |
| API approval valid | {account['api_agent_ready_read_only']} |
| Actual `par` positions | {len(account['positions'])} |
| Ordinary / trigger-aware orders | {len(account['open_orders'])} / {len(account['frontend_open_orders'])} |
| Clock | {account['clock']['state']} |
| Account technical readiness | {account['account_ready_read_only']} |

| Competition market | Account setting |
| --- | --- |
{rows}

The wallet was already funded and unified. No repeated unified-mode action was required. The local API key matched the manually verified approved address; only this API signer was used for the authorized leverage actions. No team-wallet private key, seed, signature or signed payload appears in these reports.

1x CROSS is a setting for shared collateral. It does not open a position, produce a profit, reserve the whole million-unit balance or authorize the bot to trade. It also does not make future risk disappear. Actual position size, side capacity, fees, funding, liquidity and protection still matter. The bot's one-global-position rule remains enforced.

The account audit includes `userFees`, `userRateLimit`, `activeAssetData`, positions, ordinary/trigger orders and actual fill/funding reconciliation for its explicit recorded window. No-fills accounting is not certification of real trade settlement. Budget observations are snapshots, not a permanent permission. Preserve `runtime/testnet/anchorium-bot-1/nonces.sqlite` and its configuration journal; never reset nonce history to bypass a failure.

The final local signer preflight passed after the setting changes: the API address still matches, nonce history is healthy, and a competing local owner was refused. That probe allocated no nonce, created no signature and submitted no action. Its lock scope is this host/OS user; another host has not been audited.

Evidence: {link('signer_preflight_after.json','final local signer and nonce probe')}, {link('account_check_after.json','fresh post-configuration account audit')}, {link('operating_checks_after.json','durable state and action-count checks')}.

## 3. Safety and strategy

```ini
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
```

Both remain enforced. Angel One execution remains blocked. The original NSE repository was untouched. `signal_brain.py`, eight protected strategy methods and 32 protected parameters passed the baseline comparison. VWAP, EMA, ATR, LONG/SHORT decisions, normal stops/targets, cooldowns, direction flips and strategy state behavior were not tuned.

Scanner requirements remain **300 completed bars**, **0.40% ATR floor**, **15 bps maximum spread**, **Top-3** and completed UTC inputs. No historical CSV was substituted for a current feed, no bars were invented and no strategy threshold was relaxed.

## 4. Emergency protection

The configured policy remains: **normal strategy stop + one entry ATR farther away + 0.5% execution allowance + reduce-only**. For a LONG the independent trigger is below the normal stop; for a SHORT it is above it. It protects only actual filled exposure.

**Configured: YES. Enabled: NO.** No protective order was created. A future accepted protective order can trigger during normal operation and remain on the exchange if the bot disconnects. The 0.5% allowance does not guarantee execution. Real acceptance, quantity updates and recovery still need a separately authorized controlled certification. This independent policy does not alter the normal strategy stop.

The prior approved geometry document and offline checks remain valid because the protection-policy file is unchanged: [approved protection policy](<{ROOT/'docs/practice_setup_2026-10-07/protection_configuration_approval.md'}>).

## 5. More PAPER evidence, with honest source labels

The additional 15-minute run completed before editing the helper. It used real public `par` feeds and the preserved hypothetical ledger. It finished cleanly, had **{paper['scanner_cycles']} scanner cycles**, **{paper['scanner_qualified']} qualified markets**, **{paper['local_fills']} simulated fills**, **{paper['reconnections']} reconnect**, and **zero real orders**. State and backup integrity/checksums passed. Of {paper['heartbeat_samples']} running observations, {paper['any_healthy_samples']} had at least one locally healthy market; this does not mean uninterrupted healthy data or an admitted strategy setup.

Its segment-only scanner rejections were {prior_reasons}. The persistent funnel also retains earlier runs; the corrected completion summary explicitly separates cumulative counters from this segment's counters.

After the helper change and real configuration, an additional bounded current-source PAPER run completed for **{post['finished_unix']-post['started_unix']:.1f} seconds**. It had **{post_scanner['passed']} scanner-qualified observations**, **{post_health['local_fills']} simulated fills**, **{post_health['public_stream']['reconnections']} reconnects**, and **zero real orders**. Rejections: {post_reasons}. It stopped cleanly with verified backups. Its source fingerprint matches the passing full suite and actual configuration helper.

The hypothetical PAPER balance is separate from the actual wallet. Zero fills do not establish profitable trading or actual fee/funding/P&L settlement. Public-feed and local-ledger recovery remain separate from funded position/order recovery.

The first segment retains source `{paper['source_hash']}`. The helper pacing/diagnostics fix and its regression test produce current source `{source}`. The second segment uses a new explicitly named PAPER state directory, preserving the prior ledger and recorded fingerprint. Saved hashes were not rewritten.

Evidence: {link('paper_completion_corrected.json','15-minute segment and recovery checks')}, {link('post_configuration_paper_receipt.json','current-source PAPER completion')}, {link('operating_checks_after.json','checkpoint and backup integrity')}.

## 6. What still prevents funded practice

**The current signal feed still needs usable fresh-candle evidence.** Fresh book/mark messages do not make stale completed candles valid. The earlier raw REST comparisons also showed stale or absent candle histories; the captured-response adapter checks preserved the exchange's actual completed timestamps. The exchange's internal cause is not proven. Funding or leverage changes cannot repair public candle history.

No valid setup is a legitimate `NO_TRADE`. Keep recording genuine observations. Do not lower ATR, remove the 300-bar requirement, widen spread limits, invent bars or load historical CSVs as live data.

The LONG, SHORT and funded recovery sequence is prepared in {link('next_steps.md','the inactive next-step plan')}. Those tests were not run: usable current data and separate explicit order/protection activation with a small reviewed budget are still required. Complete LONG, verify flat and reconcile actual fees/P&L before SHORT; then certify cancellation, reconnect, restart, existing-position recovery and duplicate prevention. Do not start autonomous funded practice merely because configuration passed.

## 7. Readiness now

| Item | Evidence-based status |
| --- | --- |
{flag_rows}

Account readiness refers to the saved read-only observation. PAPER operation is verified for the bounded saved runs, not for an always-on remote server. Real funded execution remains uncertified. The six research validation/promotion flags remain false; no ML model or alternate VWAP anchor was promoted. The research `PRODUCTION_CHANGED=false` flag does not mean no infrastructure changed.

## 8. Running again and hosting

The chosen host remains this Mac. No AWS deployment or background server service was installed. AWS is not required for the completed local checks. For longer sessions, keep the host awake, connected, monitored and restricted to one trader/signer owner. A future server needs its own installation, persistent paths, monitoring, backup and recovery checks.

For another PAPER session on the current unchanged source, from the project root:

```sh
.venv/bin/python scripts/run_practice.py --duration-seconds 3600 --state-directory runtime/paper/readiness-2026-10-07-paced-source --output-root docs/practice_followup_2026-10-07/paper_segments
```

In a second terminal:

```sh
.venv/bin/python scripts/check_practice_health.py --state-directory runtime/paper/readiness-2026-10-07-paced-source
```

The existing schedule is a scan every 300 seconds, management every second, and health/export every 30 seconds, subject to network latency. The completed runs stopped at their bounded deadlines; no unlabeled collector is left running. Source/policy changes require explicit checkpoint handling rather than relabeling an old ledger. Keep signer state separate from hypothetical PAPER state.

## 9. What this means for the hackathon

The infrastructure is stronger and the requested leverage mismatch is resolved. **These checks cannot prove that the frozen VWAP strategy will win.** There is still no real-trade certification or demonstrated trading advantage in these zero-fill runs. The strongest submission will show honest reproducible results, preserved strategy comparisons, real accounting evidence and reliable operation. Do not claim validated ML or winning returns that the evidence does not establish.

This report records results; it cannot unlock trading. Principal evidence hashes, Git commit/dirty state, source identity and flags are in {link('readiness.json','the machine-readable readiness file')}.
'''
(OUT/'report.md').write_text(report)
print(json.dumps(dict(report=str(OUT/'report.md'),readiness=flags,configuration_actions=applied['configuration_actions_submitted'],orders=0)))
