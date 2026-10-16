# Unsent question: exact small-position closing and protection rules on par

No message has been sent. No signed test has been performed.

The 12 October read-only inspection found that all ten official par markets have minimum lots worth less than 10 USDPR at their observed marks. Eight had two-sided books, but one lot also remained below 10 at both reviewed LONG entry and conservative stop-limit/exit prices. The other two did not have usable two-sided books. An entry above 10 does not rule out a smaller partial fill or exit remainder.

Before our first small operator-approved testnet round trip, please confirm separately:

1. Is an exact full-position opposite-side reduce-only IOC exempt from the $10 minimum on the testnet par DEX? Specify the exact conditions and fields.
2. Is a stop-limit covering the exact same small position exempt? Does `positionTpsl` versus `na`, explicit quantity versus dynamic full-position quantity, or limit versus market execution change that treatment?
3. If either is unavailable, what documented exchange-native method closes such a remainder without increasing exposure? Provide an official reference or verifiable par exchange evidence.

We retain the published general minimum and block entry pending a verified safe path. We will require separate approval of an exact bounded trade after any necessary implementation and regression tests.
