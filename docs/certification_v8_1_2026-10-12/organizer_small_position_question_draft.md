# Unsent question: closing small partial fills on par

Draft only. No message has been sent.

We are preparing one operator-approved testnet execution certification, capped at 25 USDPR and 1x CROSS. The account is currently flat. Before submitting anything, we need to confirm a partial-fill detail.

The participant guide states a $10 order minimum. An IOC entry can fill only one lot, and that can leave less than $10 of position value. For example, our 12 October public snapshot had par:BTC at about 83,936.5 with a 0.0001 BTC lot: one lot is about 8.39 USDPR. Our current adapter applies the $10 rule to every order and therefore blocks both protection and closing orders for that size.

For par perpetuals, does the exchange accept a reduce-only order that closes an entire existing position when its notional is below $10? Is that also permitted for a reduce-only stop-limit protecting the full position? If an exception exists, please confirm its exact conditions and the documented API method/fields. If it does not, what is the supported safe way to flatten a sub-minimum partial fill without increasing exposure?

We have not submitted this certification entry, increased its size, used a team-wallet signature, or assumed an undocumented exception. We will preserve bounded prices and reduce-only semantics.
