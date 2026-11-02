#!/bin/zsh
cd '/Users/adesh/Autonomous Trading Bot - Crypto ' || exit 1
'/Users/adesh/Autonomous Trading Bot - Crypto /.venv/bin/python' '/Users/adesh/Autonomous Trading Bot - Crypto /docs/carry_2026-10-25/resolve_dispatched_ioc.py'
resolve_result=$?
printf '\nResolution exited with code %s. Preserve the output above.\n' "$resolve_result"
read -r '?Press Return to close this window.'
exit "$resolve_result"
