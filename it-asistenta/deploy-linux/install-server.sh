#!/usr/bin/env bash
# ============================================================
#  Instaleaza serverul Carpatica Asistenta IT pe Linux, ca serviciu systemd.
#  Serverul asculta DOAR local (127.0.0.1:8443); Cloudflare Tunnel il publica
#  spre exterior cu TLS. Ruleaza din folderul it-asistenta:  sudo deploy-linux/install-server.sh
# ============================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # folderul it-asistenta
SVC="carpatica-asistenta"
RUNUSER="${SUDO_USER:-$USER}"

echo ">> Folder aplicatie: $HERE"
echo ">> Serviciul va rula ca utilizator: $RUNUSER"

command -v python3 >/dev/null || { echo "Instalati python3 (sudo apt install -y python3 python3-venv)"; exit 1; }

echo ">> [1/5] Creez mediul virtual si instalez dependentele..."
python3 -m venv "$HERE/.venv"
"$HERE/.venv/bin/pip" -q install --upgrade pip
"$HERE/.venv/bin/pip" -q install -r "$HERE/server/requirements.txt"

echo ">> [2/5] Configurez serverul (local + allow_insecure; TLS il pune Cloudflare)..."
cd "$HERE"
"$HERE/.venv/bin/python" - "$HERE/server/config.json" <<'PY'
import json, os, sys
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
d.update(host="127.0.0.1", port=8443, allow_insecure=True)
json.dump(d, open(p, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("   config.json actualizat.")
PY

echo ">> [3/5] Creati un tehnician (va cere o parola de minim 8 caractere):"
read -rp "   Nume utilizator tehnician [adrian]: " TECH
TECH="${TECH:-adrian}"
"$HERE/.venv/bin/python" -m server adduser "$TECH"

echo ">> [4/5] Instalez serviciul systemd ($SVC)..."
sudo tee "/etc/systemd/system/$SVC.service" >/dev/null <<EOF
[Unit]
Description=Carpatica Asistenta IT - server releu
After=network.target

[Service]
Type=simple
User=$RUNUSER
WorkingDirectory=$HERE
ExecStart=$HERE/.venv/bin/python -m server run --host 127.0.0.1 --port 8443
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now "$SVC"
sleep 2
sudo systemctl --no-pager --full status "$SVC" | head -n 8 || true

echo ">> [5/5] Token de inregistrare a laptopurilor (pentru dispozitive RustDesk):"
"$HERE/.venv/bin/python" -m server token || true

echo ""
echo "============================================================"
echo " Serverul ruleaza local pe http://127.0.0.1:8443"
echo " Urmatorul pas: Cloudflare Tunnel (vezi deploy-linux/README.md)"
echo "   -> agentii vor folosi:  wss://asistenta.carpaticaferoviar.ro/ws/agent"
echo "   -> consola:             https://asistenta.carpaticaferoviar.ro"
echo " Comenzi utile:"
echo "   sudo systemctl restart $SVC     # reporneste serverul"
echo "   sudo journalctl -u $SVC -f      # vezi jurnalul"
echo "   $HERE/.venv/bin/python -m server adduser <nume>   # (din $HERE) adauga tehnician"
echo "============================================================"
