# V7 audit notes

These notes identify the limits of the claims in the report. They are not an activation approval.

- One shared monitor observes validated decoded REST and WS inputs. Existing normalization/merge/health/scanner paths still decide what can be used. The monitor has no cache-write, signer, order or account interface.
- Logical UTC candle close is start plus 60,000 ms. Raw close-boundary minus 1 ms is retained by the actual candle record. The unfinished minute is excluded. Unknown exchange publication time stays null.
- Live REST and WS reception statistics exclude pre-start history. A missing interval at the end is censored, not assigned zero delay. Initial not-yet-observed minutes can appear in first-arrival counters; covered-response absences are reported separately.
- A current 300-minute expected window is not a shortcut for the frozen brain's complete UTC input. The last scanner request and currentness are reported independently. The two-minute freshness allowance remains unchanged.
- The repair worker keeps its proven full-window repair for short/gapped cache histories. Exact holes are recorded; the monitor is not a second downloader. Retry hints can lengthen existing backoff within 30 seconds–five minutes after at least 20 live completed REST samples. A 15-minute run may not have enough samples to activate that branch; its numerical behavior is tested offline, not claimed as demonstrated live adaptation.
- Near-ready ordering operates inside due-time cohorts. All due symbols remain in the one worker's batch, preserving the existing budgets, coalescing and reserves. No request is an exchange write.
- No external record carries a native par symbol. The isolated research library has no HTTP/native-client/live-execution imports. Its standalone capture injects fixed public read-only mainnet metadata/candle transport, with a bounded request allowance and separate artifacts.
- A source named by the organizers is a reference candidate. It does not establish equivalent volume, licensed reuse, source freshness, future-safe signal basis or a feasible trade. Full UTC and reception provenance are mandatory before feature research. All unapproved signal/outcome fields remain null.
- Native executable quotes, mark/oracle, account positions, fees and funding remain venue truth. No real wallet/account preflight is performed in this V7 task. Historical account documents remain historical.
- Core source is not changed during either public collector. A source-bound passing full regression precedes the native validation. Evidence tools under docs are separately hashed because they are outside the established active-source digest.
- No funded LONG, SHORT, protection acceptance or funded recovery is certified. PAPER/false and protection disabled remain enforced. No autonomous longer run or recurring automation is started.
