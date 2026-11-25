# CoinDCX with your ₹1,000: step by step

*25 November 2026.* All commands are typed in Terminal inside the project folder (`cd "/Users/adesh/Autonomous Trading Bot - Crypto "`).

## Start with one command (your choice on 25 Nov, 8:15 pm: trade now, at most Rs 100 loss)

```
.venv/bin/python scripts/run_compounder.py go-live --strategy intraday --equity-inr 1000 --max-loss-inr 100
```
It does everything in order and stops at the first problem:
1. writes the LIVE plan with the Rs 100 limit (no trade may risk more than a quarter of it, about Rs 25);
2. one tiny test trade (you type `PLACE ONE TEST ORDER`);
3. the real-money switch (you type the phrase shown on screen);
4. starts the bot in the background, 24/7, and shows when its next decision is.

The Rs 100 limit: the bot never opens a trade that could take your money (after tax) below Rs 900 if every
stop-loss were hit, and if it ever reaches Rs 900 it closes everything and stops for good. A sudden crash
can slip a few rupees past it. Only one live bot can run on the account at a time.

## The two plans

| | **Daily plan (recommended)** | Intraday plan (what you asked for) |
|---|---|---|
| What it does | Once a day (05:30 IST) it checks 10 coins. It goes **long** when a coin breaks its 55-day high and **short** when it breaks its 55-day low. A stop-loss sits on CoinDCX 24/7 | Every hour it goes long or short with the day's market direction. It closes everything by 05:30 IST every day |
| Tested 2024–Nov 2026 with your ₹1,000 (CoinDCX fees, slippage, funding and the 30% crypto tax) | ₹1,000 → **₹1,010**. Lowest ₹498, highest ₹2,179 | ₹1,000 → **₹186**. It also lost before tax: fees eat the small hourly moves |
| Trades | about 1–2 a month | about 5 a month (many more signals, mostly skipped by the risk limits) |
| Practice bot now | `mandate_paper_coindcx_rs1000_daily.json` | `mandate_paper_coindcx_rs1000_intraday.json` |

Both plans compound: every profit, after setting aside the 31.2% tax, makes the next trade bigger. Both trade long or short with up to 10x leverage. The leverage for each trade is lowered when its stop-loss is far away, so CoinDCX never liquidates the position before the stop-loss is hit. With ₹1,000, the coins with a $6 minimum order (DOGE, XRP, ADA, TRX, AVAX, BNB, SOL) get traded. BTC ($60 minimum) and ETH/LINK ($24) are skipped automatically when they would risk too much.

## Steps

**1. Create the API key** on the CoinDCX website (API dashboard, `coindcx.com/api-dashboard`):
- Name it `compounder`.
- Give it trading permission only. **Do not enable withdrawals** if that option is shown.
- Copy the **key** and the **secret**. The secret is shown only once.
- Never paste the secret into a chat (including this one), an email or a file.

**2. Save the key on your Mac** (the typing is hidden; it is saved only to `~/.anchorium/coindcx_api.json`, readable by you alone):
```
.venv/bin/python scripts/run_compounder.py store-coindcx-key
```

**3. Put ₹1,000 into the futures wallet.**
- In the CoinDCX app, deposit ₹1,000 (UPI or bank).
- Transfer it to **Futures** as **INR**.
- The bot trades INR-margined futures: no USDT purchase is needed. CoinDCX converts at its own rate (₹106 per USDT today).

**4. Check that the connection works (read-only, nothing is traded):**
```
.venv/bin/python scripts/run_compounder.py make-coindcx-mandate --strategy daily --equity-inr 1000
.venv/bin/python scripts/run_compounder.py live-preflight --mandate docs/compounder_2026-11-25/mandate_live_coindcx_daily.json
```
- It should end with `PREFLIGHT OK`.
- Send me the output. It contains balances, never your key or secret.
- I check that CoinDCX's real replies match what the bot expects before any order is placed.

**5. One tiny test trade (about ₹1–3 in fees):**
```
.venv/bin/python scripts/run_compounder.py live-smoke-test --mandate docs/compounder_2026-11-25/mandate_live_coindcx_daily.json
```
- It buys the minimum DOGE (about $6.30) at 2x and sets a stop-loss, then closes it at once. You type `PLACE ONE TEST ORDER` to allow it.
- While the test trade is open it reads your wallet and the position from CoinDCX and checks the numbers the bot relies on: the wallet total (balance + locked margin), the liquidation price and the fills in the trade history.
- It ends with `SMOKE TEST OK`. If it says `SMOKE TEST NEEDS A LOOK: ...`, stop there and send the output.
- Check the trade in the app afterwards.

**6. Switch on real trading.** You read the tested numbers and type the phrase yourself:
```
.venv/bin/python scripts/run_compounder.py activate-live --mandate docs/compounder_2026-11-25/mandate_live_coindcx_daily.json
```
Then start the bot so it keeps running 24/7, even after you close the Terminal window:
```
nohup caffeinate -is .venv/bin/python scripts/run_compounder.py live --mandate docs/compounder_2026-11-25/mandate_live_coindcx_daily.json >> runtime/compounder/logs/mandate_live_coindcx_daily.log 2>&1 &
```
The first decision is at the next 05:30 IST daily close; a breakout that happened before the start is never chased.
For the intraday plan, use `--strategy intraday` in step 4 and `mandate_live_coindcx_intraday.json` in steps 4–6. The activation screen shows its tested result (₹1,000 → ₹186) before you type.

**7. Every day:**
- `.venv/bin/python scripts/run_compounder.py board` shows all practice bots and, once it has started, the LIVE bot.
- `status --mandate docs/compounder_2026-11-25/mandate_live_coindcx_daily.json` shows the live one.
- Keep the Mac plugged in with the lid open while it runs. If it sleeps, the stop-losses on CoinDCX still protect open trades, but no new decisions are made.

**8. Rules that keep the bot safe:**
- **Don't trade by hand in the same CoinDCX futures account.** The bot closes any position it does not recognise and stops opening new ones until you check (`LIVE_UNKNOWN_POSITION`).
- Don't add money to win back a loss.
- To stop new trades: `no-entries --mandate ...`. To close everything: `flatten --mandate ...`. To stop the bot: `stop --mandate ...`.
- Automatic pauses:
  - Down 30% in a day: no new trades until the next day.
  - Down 60% from the best level: no new trades until you run `reset-halt`.

## What the bot does on every live trade

1. It reads the position fresh from CoinDCX and refuses unless that coin is flat with no pending orders.
2. It sets the leverage for that coin: up to 10x, lower when the stop-loss is far.
3. It sends one market order. CoinDCX has no duplicate protection, so a lost reply is never resent: the bot re-reads the position and adopts whatever CoinDCX actually holds.
4. It places the stop-loss on CoinDCX at once. It checks CoinDCX's liquidation price is beyond the stop-loss. If either fails, it closes the trade immediately.
5. It books the real fill price, fees and funding. 31.2% of each winning trade's profit, before fees, is reserved for tax. Everything else compounds into the next trade.
6. To exit, it closes the position first and cancels the stop-loss after. If CoinDCX refuses or times out, the stop-loss stays in place and the exit is retried every 20 seconds until CoinDCX confirms the position is closed.
7. If the bot ever finds one of its positions without a stop-loss (for example, the Mac shut down between the fill and the stop), it closes that position.
8. A CoinDCX error or a lost connection never stops the bot: it writes the error to the log and tries again on the next loop. Your money's value is CoinDCX's wallet total (balance + locked margin + open profit/loss).
