# Offline verification coverage

The previous full suite contained 1,301 tests. This change adds 38 cases, including parameter variants. The final full receipt is authoritative; no public soak starts before that receipt passes and matches the current source.

| Requirement | Actual test evidence |
|---|---|
| One stale market cannot block healthy markets | stale BTC/healthy ETH, partial-health real stream/PAPER composition, original four independent-clock tests |
| All markets/global failures still degraded | all inputs bad, transport/account/budget/accounting/worker/subscription failure variants |
| Complete candle integrity before brain | gap, duplicate, future, OHLC, numeric volume and identity variants |
| Bounded actual candle recovery | missing older bar backfilled by actual fake-public REST, empty/error/CSV-string/malformed responses remain quarantined |
| Single worker automatic restoration | initial empty BTC history repaired on the existing socket, without reconnect/process restart |
| Known-symbol invalid data stays scoped | invalid candle, mixed batch and malformed context; ETH remains usable |
| Wrong venue/protocol fails closed | native symbol and unrecognized public channel |
| Future prices cannot poison cache | REST and WebSocket future-book variants |
| Expired reconnect | exactly 40/40 subscriptions restored, zero duplicates, bad BTC remains quarantined |
| Scanner strategy gate | rejected BTC never calls brain or produces a signal; healthy symbols follow normal path |
| Reporting | human-readable per-market/subscription/account/feed/trade/global output; partial health exits 0 and genuine failures exit 2 |
| Formal evidence gates | no market/one sample/bad tape checksum/unstopped workers/no safe scanner data/unsafe PAPER flags fail closed; no trade required |
| Budget/coalescing | existing feed-hardening concurrent-read/reserve/cancel tests and production reliability tests reused |
| Strategy/management parity | freeze + existing state/cooldown/direction/position-management regression unchanged |

Offline fake data tests exercise code behavior. They never certify a funded wallet, actual fills, exchange protection, or strategy profits. New public evidence has independent source/checkpoint/state identity.
