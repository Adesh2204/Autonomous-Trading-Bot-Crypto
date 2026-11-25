# Filing tax on the bot's crypto trades: step by step (no CA)

*Prepared 25 November 2026. This is general information, not professional tax advice. India's rules for crypto futures are not settled. This guide follows the **strict reading** so that you never pay too little. If your yearly profit becomes large, a one-time check by a CA (often ₹1,000–3,000) is worth it.*

## The rules in plain words

1. **30% + 4% cess = 31.2%** on the profit of every winning trade (the crypto "VDA" rule).
2. **Losses don't help.** A losing trade does not reduce the tax on a winning one, and it cannot be carried to next year.
3. **Fees can't be deducted.** Tax is on (sell value − buy value).
4. **The usual tax-free limit doesn't protect crypto profit.** Most guides say the basic exemption and the Section 87A rebate do not apply to it. A few people are contesting this in appeals, so assume you pay 31.2% even if your other income is small.
5. **Financial year (FY):** 1 April to 31 March. Trades from today (Nov 2026) are in **FY 2026-27**, filed by **31 July 2027**. From 1 April 2026 the new Income-tax Act 2025 applies, so section numbers and form layouts may look different. The 30% crypto rate and 1% TDS were carried over.

The bot already follows rules 1–3: it sets aside 31.2% of each winning trade's profit (before fees, plus any funding received) and never trades with that money. That reserve is your tax money.

## During the year

| When | What you do |
|---|---|
| Any time | Nothing to file. The bot records every trade in USD and INR |
| 15 Jun, 15 Sep, 15 Dec, 15 Mar | **Advance tax**, only if your total tax for the year (all income) will be ₹10,000 or more. With ₹1,000 traded this is very unlikely. If it applies, pay 15%, 45%, 75% and 100% of the year's tax by those dates |
| Whenever you take money out | Withdraw the profit and the reserved tax money from CoinDCX to your bank. Keep the tax part aside. INR-margined futures normally have no 1% TDS; if any TDS is deducted it appears in your Form 26AS and counts toward your tax |

## After 31 March (filing, April to July)

**Step 1. Make the register.** It is a CSV with one line per trade, all in rupees:
```
.venv/bin/python scripts/run_compounder.py tax-report --mandate docs/compounder_2026-11-25/mandate_live_coindcx_daily.json --fy 2026
```
Columns:
- date of acquisition (buy)
- date of transfer (sell)
- cost of acquisition (buy value)
- consideration received (sell value)
- income (sell − buy)
- fees
- funding
- tax at 31.2%

For a short trade the sell comes first; the register handles that.

**Step 2. Download CoinDCX's own statements.** In the app: futures trade history and P&L / tax reports for 1 April to 31 March. The two should match. If they differ, use CoinDCX's figures and tell me so I can find the cause.

**Step 3. Check what the tax department already knows.**
- Log in to **incometax.gov.in** and open **AIS** (Annual Information Statement) and **Form 26AS**.
- Indian exchanges report crypto transactions, and any TDS shows there. Your return must agree with it.

**Step 4. Pay the tax before filing.**
- Amount: the **sum of the "Tax 31.2%" column**, plus tax on your other income if any.
- On incometax.gov.in: **e-Pay Tax → Income Tax → Self-Assessment Tax (300)**. This was called "Challan 280".
- Save the challan receipt (BSR code, challan number, date).

**Step 5. File the return by 31 July.**
- **Form:** ITR-2 if you have no business income, for example salary or no income besides crypto. List the trades under **Schedule VDA** (head: capital gain). If you treat trading as your business, use ITR-3; the tax is the same 30%.
- **Schedule VDA:** one row per trade from the register.
  - Winning trades: enter the income.
  - Losing trades: the schedule reports them as nil, and they don't offset anything.
- **Funding:** if the register shows net funding *received*, add it to income from other sources. Funding paid is not deductible.
- **Tax paid:** enter the self-assessment challan from Step 4 in the "taxes paid" section. Enter any TDS from Form 26AS.
- **Verify:** check that tax payable shows 0 (already paid), then submit. **E-verify within 30 days** (Aadhaar OTP).

**Step 6. Keep the records for 6 years:**
- the register CSVs
- CoinDCX statements
- challan receipts
- the filed return (ITR-V)
- `runtime/compounder/.../trades.jsonl`

## If you trade at a loss for the year

There is no tax to pay on the losses, but still **file** if your total income needs a return or if AIS shows crypto activity. Report the trades in Schedule VDA (losses as nil). Not filing while AIS shows crypto trades can bring a notice.

## Missed the 31 July deadline?

You can file a **belated return** until 31 December. The late fee is ₹1,000 if total income is up to ₹5 lakh (₹5,000 above that), plus interest on unpaid tax.
