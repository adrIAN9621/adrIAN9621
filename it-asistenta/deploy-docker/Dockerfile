# syntax=docker/dockerfile:1
# ----------------------------------------------------------------------------
#  Carpatica Asistență IT – server releu (FastAPI + WebSocket), pentru platforma
#  Docker + Caddy. Ascultă pe 0.0.0.0:8080 în container; TLS îl pune Caddy.
#  Date persistente în /data (config.json + baza SQLite). Rulează ca utilizator
#  neprivilegiat, rootfs read-only (doar /data și /tmp inscriptibile).
# ----------------------------------------------------------------------------
FROM python:3.12-slim

# Doar dependențele de runtime (pytest/httpx din requirements.txt sunt pentru teste).
RUN pip install --no-cache-dir \
      "fastapi>=0.110" \
      "uvicorn[standard]>=0.29" \
      "websockets>=12" \
      "cryptography>=42"

WORKDIR /app
COPY server /app/server
COPY deploy-docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/entrypoint.sh \
 && useradd --system --uid 10001 --home /app --shell /usr/sbin/nologin asistenta \
 && mkdir -p /data && chown -R asistenta:asistenta /data

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ASISTENTA_CONFIG=/data/config.json \
    PORT=8080

USER asistenta
EXPOSE 8080

# Stare pentru Docker/Caddy (endpoint public, fără date sensibile).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/healthz',timeout=3).status==200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
