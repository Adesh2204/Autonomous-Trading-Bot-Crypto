# Scoped configuration pacing fix

The actual first apply attempt stopped before HTTP transmission. A test running the complete existing CLI, real account readiness, rate manager, durable nonce handling and official SDK with an ephemeral signer/fake exchange reproduced the same failure: repeated account/metadata checks consumed the allowed decision-request weight before the first configuration action.

The fix must wait for local read weight to expire before starting another complete readiness check or ten-market verification. It must preserve the configured rate ceiling and safety reserve, perform the complete fresh readiness check after waiting, check approval expiry during the wait, retain every exact-action/nonce/account-ownership check, and never retry a signed action with an uncertain outcome. Each sleep is at most one second and total waiting per read group is bounded. Readiness failures must retain sanitized reason codes, clock and rate observations.

The 15-minute PAPER segment is deliberately allowed to finish on its original source fingerprint before applying this infrastructure change. Its receipt must keep that original fingerprint. Its hypothetical ledger must not be relabeled as having run the revised helper source.

This changes the leverage configuration helper only. Production orders remain locked, independent protection remains disabled and the strategy remains frozen. A synthetic ten-market success validates software composition; the separately authorized real configuration needs its own exchange readback and account audit.
