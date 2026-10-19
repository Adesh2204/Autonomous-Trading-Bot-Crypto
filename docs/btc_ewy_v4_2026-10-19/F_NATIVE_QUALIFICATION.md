# F — Independent native/residual qualification

Both markets remain UNQUALIFIED. Native proposals are unsigned, source-bound observations, not executable approvals.

- pas:BTC: runtime lot 0.00001; proposed full quantity 0.00030; actual entry/stop acceptance/armed/triggered/child/SELL fill/residual proof: absent. One-lot stop notional 0.81248 TEST USDP, below the ordinary minimum.
- pas:EWY: runtime lot 0.001; proposed full quantity 0.159; actual entry/stop acceptance/armed/triggered/child/SELL fill/residual proof: absent. One-lot stop notional 0.15400 TEST USDP, below the ordinary minimum.

Each bounded review specifies one entry, independent mark-trigger reduce-only Stop Limit, at most six signed actions, five-minute authority, at most 120 seconds natural-trigger wait with cleanup reserve, one owned cancellation round and at most two resolved exact-residual IOC attempts. None is authorized. Partial fills, rejected stops, trigger without fill, gaps, subminimum residuals, disconnects, emergency closure and terminal accounting are software-tested offline; neither a test nor PAR IOC evidence qualifies PAS.

No subminimum native/cleanup dispatch exception is implemented or granted without admissible route-specific evidence and separately reviewed authority. This prevents an unsafe qualification BUY from creating exposure that cannot be closed under current guards. There is no fabricated native certificate or execution command. Future BTC qualification cannot qualify EWY.
