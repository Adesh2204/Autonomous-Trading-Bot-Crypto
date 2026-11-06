#!/bin/zsh
cd '/Users/adesh/Autonomous Trading Bot - Crypto ' || exit 1
'/Users/adesh/Autonomous Trading Bot - Crypto /.venv/bin/python' '/Users/adesh/Autonomous Trading Bot - Crypto /docs/carry_2026-10-25/configure_carry_markets.py'
configuration_result=$?
printf '\nConfiguration helper exited with code %s. Preserve the output above.\n' "$configuration_result"
read -r '?Press Return to close this window.'
exit "$configuration_result"
