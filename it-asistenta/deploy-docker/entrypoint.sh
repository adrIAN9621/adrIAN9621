#!/bin/sh
# ----------------------------------------------------------------------------
#  Pregătește /data/config.json la pornire și lansează serverul.
#  Cheile de rețea/stocare sunt impuse de container (mereu suprascrise), iar
#  secretele (ingest_token, enc_secret) sunt generate și păstrate de server în
#  același fișier, deci supraviețuiesc reporniri și actualizări de imagine.
# ----------------------------------------------------------------------------
set -eu

CONFIG="${ASISTENTA_CONFIG:-/data/config.json}"
PORT="${PORT:-8080}"

python - "$CONFIG" "$PORT" <<'PY'
import json, os, sys

path, port = sys.argv[1], int(sys.argv[2])
data = {}
if os.path.isfile(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        data = {}

# Chei gestionate de container (rețea + stocare) — mereu impuse.
data.update(
    host="0.0.0.0",
    port=port,
    allow_insecure=True,        # TLS îl termină Caddy; în rețeaua internă e HTTP
    certfile="",
    keyfile="",
    db_path="/data/asistenta.db",
    trust_proxy=True,           # preia IP-ul real al clientului din X-Forwarded-For
    forwarded_allow_ips="*",    # doar Caddy ajunge la container (niciun port publicat)
)

os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
print("[entrypoint] config pregătit:", path)
PY

exec python -m server run --host 0.0.0.0 --port "$PORT"
