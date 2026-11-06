# Always-on VPS for the Anchorium runtime (Phase 5)

**Status:** prepared, not enabled. Phase 3 is NO-GO, so the bot stays flat. Install this so a future GO doesn't depend on the MacBook. The entrypoint idles until you explicitly set `ANCHORIUM_RUN=continuous`.

## What it guarantees

- **Auto-restart.** Docker uses `restart: unless-stopped`; systemd uses `Restart=on-failure`. A `stop.flag` still ends a run cleanly with no restart.
- **Reconcile on boot.** `deploy/vps/boot.py` reads `pas` positions, open orders and the last 24 h of fills from the exchange before anything else. It writes them to `runtime/vps/boot_report.json`. If that read fails, the bot never starts trading. The runtime then reconciles again on start: account recovery, adoption of any untracked position, and an exchange-fill reconcile.
- **Secrets via env only.** The API key lives in `/etc/anchorium/bot.env` (mode 600). It is never in the repo or the image; the build fails if a `.env` file is present.

## Step by step (Ubuntu 24.04, 1 vCPU / 1 GB is enough)

1. **Create the server** in a region close to Hyperliquid (Tokyo, `ap-northeast-1`, has the lowest latency). Allow SSH only; the bot needs no inbound ports.
2. **Base setup**, as root:
   ```bash
   apt update && apt -y upgrade && apt -y install git docker.io docker-compose-v2 chrony
   timedatectl set-timezone UTC && systemctl enable --now chrony   # the clock-health monitor needs NTP
   useradd -m -s /bin/bash anchorium && usermod -aG docker anchorium
   ```
3. **Code.** Use the exact commit whose regression receipt is signed. The release gate checks the source hash.
   ```bash
   sudo -iu anchorium git clone <your repo URL> /opt/anchorium && cd /opt/anchorium && git checkout <released commit>
   ```
   Copy `docs/<session>/mandate.json` and its `regression_release/test_receipt.json` from the Mac if they are not committed.
4. **Secrets.**
   ```bash
   sudo install -d -m 700 -o anchorium /etc/anchorium
   sudo install -m 600 -o anchorium deploy/vps/bot.env.example /etc/anchorium/bot.env
   sudo -u anchorium nano /etc/anchorium/bot.env      # paste API_WALLET_PRIVATE_KEY; leave ANCHORIUM_RUN unset
   ```
   Remove the key from the Mac's `.env` after the VPS has taken over. Two hosts must never trade one account at the same time.
5. **State directories.**
   ```bash
   sudo install -d -m 700 -o 10001 /var/lib/anchorium/runtime
   ```
6. **Build and start in report-only mode**, then check the boot report:
   ```bash
   cd /opt/anchorium && docker compose -f deploy/vps/docker-compose.yml up -d --build
   docker compose -f deploy/vps/docker-compose.yml logs --tail 20   # expect decision IDLE_TRADING_NOT_ENABLED, flat=true
   ```
7. **Run the regression on the VPS checkout** (it needs `.git` for the baseline tag, so not inside the image):
   ```bash
   cd /opt/anchorium && python3.12 -m venv .venv && .venv/bin/pip install -r algo-trading-bot/requirements.txt
   git fetch --tags && .venv/bin/python docs/continuous_2026-10-24/run_regression.py
   ```
8. **Only after a GO and your written approval:** run the mandate `prepare` step, set `ANCHORIUM_RUN=continuous` in `/etc/anchorium/bot.env`, remove `runtime/continuous/stop.flag`, then:
   ```bash
   docker compose -f deploy/vps/docker-compose.yml up -d
   ```
9. **Stopping.** `touch /var/lib/anchorium/runtime/continuous/stop.flag && docker compose -f deploy/vps/docker-compose.yml stop`. SIGTERM has a 90 s grace period for the flatten-and-verify path. Then confirm 0/0 on the exchange.

### systemd instead of Docker

```bash
cd /opt/anchorium && python3.12 -m venv .venv && .venv/bin/pip install -r algo-trading-bot/requirements.txt
sudo cp deploy/vps/anchorium-continuous.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl enable --now anchorium-continuous && journalctl -u anchorium-continuous -f
```

## Until the VPS takes over

Keep the MacBook plugged in with the lid open, and run `caffeinate -dims` in a terminal. The supervisor already wraps the runtime in `caffeinate -is`, but the lid and power settings still apply.
