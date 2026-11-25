# Compounder: setup and operations

*25 November 2026.* Your CoinDCX steps: [COINDCX_LIVE_STEPS.md](COINDCX_LIVE_STEPS.md). Tax filing: [TAX_FILING_GUIDE.md](TAX_FILING_GUIDE.md). The research verdict is in [research_results.md](research_results.md). Short version: **NO-GO** for real money under India's conservative per-trade crypto tax rule. The bots run in PAPER mode on live prices. Live trading exists for Hyperliquid only. It stays locked until you complete every step in section 3 yourself.

## 1. What runs now

Eight practice (paper) bots run 24/7 on each venue's live public prices, order books and funding (no keys, no orders):

| Bot (as shown by `board`) | Mandate | Run dir |
|---|---|---|
| Hyperliquid, tested rules (long only), $1,000 | `mandate_paper.json` | `paper-af21003423` |
| Hyperliquid, long+short, $1,000 | `mandate_paper_ls.json` | `paper-7b94acb188` |
| CoinDCX, tested rules (long only), $1,000 | `mandate_paper_coindcx.json` | `paper-16dd652521` |
| CoinDCX, long+short, $1,000 | `mandate_paper_coindcx_ls.json` | `paper-7510a547c1` |
| Hyperliquid, Rs 1,000, long+short, 10x | `mandate_paper_inr1000_hyperliquid.json` | `paper-349d114eba` |
| CoinDCX, Rs 1,000, DAILY long+short, INR margin (practice copy of the live plan) | `mandate_paper_coindcx_rs1000_daily.json` | see `board` |
| CoinDCX, Rs 1,000, INTRADAY long/short by market direction, INR margin | `mandate_paper_coindcx_rs1000_intraday.json` | see `board` |
| Delta India, Rs 1,000, long+short, 10x | `mandate_paper_inr1000_delta.json` | `paper-a5d5acef35` |

All seven trade the same ten coins (BTC, ETH, BNB, SOL, XRP, ADA, AVAX, DOGE, TRX, LINK) with the same daily 55/20 breakout rules. They differ only in venue (prices, fees, minimum order sizes, funding), money, and whether shorts are allowed.

The Rs 1,000 bots ($9.51) are high risk by design: 10x leverage setting. When the normal 2%-risk size is below the venue's minimum order, the bot takes the minimum order instead, but only if that order's stop risk is at most 20% of the account. All open stop risks together are capped at 40%. Their pauses: 30% down in a day stops entries until the next day; 60% below the peak stops entries until `reset-halt`.

Every 20 seconds each bot reads marks and funding and checks every open position's stop; funding is booked as each venue settles it. After each daily close (00:00 UTC = 05:30 IST) it runs exits, then entries. Fills are simulated by walking that venue's real order book at that moment.

```bash
.venv/bin/python scripts/run_compounder.py board                                    # ONE TABLE: every bot, money after tax
.venv/bin/python scripts/run_compounder.py status --mandate docs/compounder_2026-11-25/mandate_paper_inr1000_coindcx.json
.venv/bin/python scripts/run_compounder.py trades --mandate docs/compounder_2026-11-25/mandate_paper_inr1000_coindcx.json
.venv/bin/python scripts/run_compounder.py stop --mandate FILE      # ends that bot's loop (state is kept; `paper` resumes it)
.venv/bin/python scripts/run_compounder.py no-entries --mandate FILE
.venv/bin/python scripts/run_compounder.py flatten --mandate FILE   # close that bot's positions, keep running
```

### Venue facts used by the bots (read from the public APIs on 25 Nov 2026)

| | Hyperliquid | CoinDCX futures | Delta Exchange India |
|---|---|---|---|
| Smallest order | $10 for every coin | $60 BTC, $24 ETH/LINK, **$6** BNB/SOL/XRP/ADA/AVAX/DOGE/TRX | one contract: 0.001 BTC, 0.01 ETH, 0.1 BNB, 1 SOL/XRP/ADA/AVAX/TRX/LINK, 100 DOGE |
| Fees (taker) | 0.045% | 0.05% + 18% GST | 0.05% + 18% GST |
| Max leverage (these coins) | 10x to 40x | 5x (SOL) to 25x | 50x to 200x |
| Funding | hourly | every 8 h (same rate as Binance) | every 8 h |
| Money in | USDC on Arbitrum from a wallet | INR (UPI/bank) | INR |
| Live connection in this bot | built (locked) | **built (locked)**: see [COINDCX_LIVE_STEPS.md](COINDCX_LIVE_STEPS.md) | not built |

What "after-tax equity" means: equity − tax already reserved − tax that open winners would owe if closed now. Only this number is used to size the next trade, so profits compound **after** fees, slippage, funding and tax.

### Keeping it on 24/7

A MacBook sleeps on battery or with the lid closed (`caffeinate -is` only holds on AC). While the Mac sleeps the paper bot is blind. On wake it replays the gap on 1-minute candles to see whether a stop was hit. For real 24/7 use a small Linux server: steps 1 to 3 of `deploy/vps/SETUP.md`, then `deploy/compounder/compounder-paper@.service`.

## 2. Built-in protections

| Protection | Rule |
|---|---|
| Hard stop | 2 × ATR from the fill. Paper: triggers on the mark price. Live: a reduce-only stop-market order rests on the exchange, so it works even if the bot is down |
| Unprotected position | If a live stop cannot be placed, the position is closed at once |
| Daily loss pause | After-tax equity down 8% on the UTC day: no new entries until the next day |
| Drawdown halt | After-tax equity 45% below its peak: no new entries until a human runs `reset-halt` |
| Order price band | Market orders are IOC limits at most 0.5% through the touch (never a sweep); paper refuses fills more than 1% from mid or thinner than the book |
| Stale data | A coin whose daily candle is not final is skipped for that bar |
| Error pause | 5 consecutive step errors: no entries for 1 hour |
| Operator files | `STOP`, `NO_ENTRIES`, `FLATTEN` in the run directory |

## 3. Going live on Hyperliquid with MetaMask or Brave Wallet (you do every step)

The bot never holds your main wallet's key. It uses a Hyperliquid **API wallet** (agent): that key can place and cancel orders for your account but **cannot withdraw or transfer** funds.

1. **Fund the account.**
   - Buy USDC (or USDT, then swap) on an Indian exchange with INR.
   - Withdraw it to your MetaMask or Brave Wallet address on the **Arbitrum** network. Keep a little ETH on Arbitrum for the deposit's gas fee.
   - Open app.hyperliquid.xyz, connect the wallet, and deposit USDC. Hyperliquid's minimum deposit is 5 USDC; smaller deposits are lost. Withdrawing back costs 1 USDC.
   - Check that Hyperliquid's terms allow use from your location.
2. **Create the API wallet.** On app.hyperliquid.xyz, go to More → API. Name it, generate it and authorize it with your wallet. Copy the private key it shows **once**.
3. **Store the key** (hidden prompt; saved to `~/.anchorium/compounder_agent.key`, mode 0600, outside the repo):
   `.venv/bin/python scripts/run_compounder.py store-agent-key`
4. **Write the live mandate.** Use your **main** wallet address and the USD amount you deposited:
   `.venv/bin/python scripts/run_compounder.py make-live-mandate --account 0xYOURADDRESS --equity 1000`
5. **Activate.** In a terminal, you read the research verdict and type the phrase yourself:
   `.venv/bin/python scripts/run_compounder.py activate-live --mandate docs/compounder_2026-11-25/mandate_live.json`
6. **Preflight** (read-only). It checks that the agent is approved for your account, the account is funded, and there are no positions or orders the bot does not own:
   `.venv/bin/python scripts/run_compounder.py live-preflight --mandate docs/compounder_2026-11-25/mandate_live.json`
7. **Run.** It sets cross leverage (5x by default) on the ten coins once, then trades:
   `.venv/bin/python scripts/run_compounder.py live --mandate docs/compounder_2026-11-25/mandate_live.json`

Run live on one machine only. Two hosts trading one account at the same time will fight each other.

### How much money is enough

Hyperliquid's minimum order is $10. At 1% risk with a 2-ATR stop (10 to 17% away for most coins right now), a position is about 6 to 10% of equity. Below about **$200** most entries are under the minimum and get skipped. ₹1,000 (about $9.50 at today's USDT/INR of ₹105) is too small for any risk-controlled leveraged position on Hyperliquid or CoinDCX. CoinDCX's BTC futures minimum is $60 per order.

## 4. CoinDCX instead of a wallet

Not built yet. Its public futures data works: candles, order book, instruments. BTC/USDT perp: up to 20x, maker 0.02% / taker 0.05% plus 18% GST, minimum order $60, funding every 8 h. A live adapter needs a CoinDCX API key created **with trading permission only (no withdrawal)** and IP-whitelisted.

It may matter for tax. INR-settled futures on an Indian exchange are the case where some CAs file profit as business income instead of the 30% VDA rule. That is the only tax reading under which the tested rules made clear money: +40 to +52% over 2024 to 2026 on CoinDCX-like costs, against +15 to +18% under the VDA rule.

## 5. Tax handling in the bot

| Item | How the bot handles it |
|---|---|
| Default rule | `VDA_PER_TRADE`: 31.2% (30% + 4% cess) of every profitable closed trade is reserved and never traded. Losses offset nothing |
| Alternative | `BUSINESS_NET_ANNUAL`: tax on each financial year's net profit (April to March), losses carried forward 4 years. Set `tax.mode` in the mandate only if your CA files it that way |
| Records | `trades.jsonl` has every closed trade in USD and in INR (CoinDCX USDT/INR at the close), with the tax reserved |
| 1% TDS | Deducted when you sell crypto for INR on an Indian exchange. It is credited against your tax, but it is cash you do not have until you file |
| GST | 18% on Indian exchange fees (included in the CoinDCX cost profile) |

The rules for crypto futures are not settled in India. The bot's numbers are for planning; your CA decides the filing.
