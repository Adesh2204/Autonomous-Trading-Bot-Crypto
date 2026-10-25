# Anchorium continuous runtime: always-on VPS image (Phase 5).
# Secrets never enter the image: API_WALLET_PRIVATE_KEY comes from the env file at run time.
FROM python:3.12.5-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC \
    EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false
RUN useradd --create-home --uid 10001 anchorium
WORKDIR /app
COPY algo-trading-bot/requirements.txt /app/algo-trading-bot/requirements.txt
RUN pip install --no-cache-dir -r /app/algo-trading-bot/requirements.txt
COPY --chown=anchorium:anchorium . /app
# The repo must not carry a key file into the image.
RUN test ! -e /app/.env && test ! -e /app/algo-trading-bot/.env
USER anchorium
# Boot: read-only exchange reconcile report first, then the supervisor (which reconciles again on start).
ENTRYPOINT ["python3", "deploy/vps/boot.py"]
