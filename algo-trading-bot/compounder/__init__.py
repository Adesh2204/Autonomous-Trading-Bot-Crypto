"""After-cost, after-tax compounding trend bot (Hyperliquid mainnet first).

Every module here is pure and deterministic except ``paper_runner``/``hl_live`` which talk to
public market data (paper) or, only after the human's explicit activation, the exchange.

Money flow the bot reports:
    gross P&L  - exchange fees (+ GST where the venue charges it) - slippage - funding paid
    + funding received = net P&L
    net P&L    - tax reserve (Indian VDA rule by default: 31.2% of each winning trade, losses
                 not deductible) = after-tax P&L, which is the only part that is compounded.
"""
