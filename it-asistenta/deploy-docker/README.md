# Carpatica Asistență IT – instalare pe platforma Docker + Caddy

Acest pachet pune serverul de asistență (consola tehnicienilor + releul WebSocket
pentru agenți și dispozitivele nesupravegheate) în platforma comună Docker + Caddy,
la adresa **https://asistenta.carpaticaferoviar.ro**.

Convenții respectate:

- Aplicația ascultă pe `0.0.0.0:8080` **doar în rețeaua internă** `web`; **niciun
  port nu e publicat pe host**. Accesul din afară trece exclusiv prin Caddy (HTTPS).
- Date persistente în volum (`/srv/apps/asistenta/data` → `/data`): `config.json`
  (inclusiv secretele generate automat) și baza SQLite.
- Container neprivilegiat, rootfs `read_only`, doar `/data` și `/tmp` inscriptibile.
- Endpoint de stare `GET /healthz` (fără date sensibile) pentru Docker și Caddy.
- Nu se pornește un al doilea Caddy și nu se ating celelalte aplicații de pe server.

Toate comenzile marcate se rulează pe server, prin SSH, cu contul autorizat al
platformei. Înlocuiți data din tag-ul imaginii (`20261030-1`) la fiecare versiune nouă.

---

## 1. Verificări înainte (descoperirea infrastructurii)

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
docker network ls | grep -w web            # rețeaua comună a lui Caddy trebuie să existe
docker inspect caddy --format '{{json .Mounts}}'   # unde e montat Caddyfile-ul
df -h / /srv && free -h
```

Rețineți: numele containerului Caddy, calea montată a `Caddyfile` (în exemple
`/srv/apps/proxy/Caddyfile`) și faptul că rețeaua `web` există. Dacă rețeaua se
numește altfel, folosiți numele real în `.env` (`CADDY_NETWORK=...`).

## 2. Aducerea surselor pe server

**Varianta A – git (dacă serverul are acces la GitHub):**

```bash
STAGE=$(mktemp -d /tmp/asistenta-release.XXXXXX)
git clone --depth 1 https://github.com/adrIAN9621/adrIAN9621 "$STAGE/repo"
cd "$STAGE/repo/it-asistenta"
```

**Varianta B – fără git pe server**, de pe mașina voastră (PowerShell/bash), apoi scp:

```bash
# pe mașina cu codul, în folderul it-asistenta:
tar -czf asistenta-20261030-1.tar.gz server deploy-docker .dockerignore
scp asistenta-20261030-1.tar.gz <user>@<server>:~/
# pe server:
STAGE=$(mktemp -d /tmp/asistenta-release.XXXXXX)
tar -xzf ~/asistenta-20261030-1.tar.gz -C "$STAGE"
cd "$STAGE"
```

## 3. Construirea imaginii

```bash
IMAGE=carpatica-asistenta:20261030-1
docker build -f deploy-docker/Dockerfile -t "$IMAGE" .
# verificare rapidă: rulează ca utilizator neprivilegiat (uid 10001)
docker run --rm --network none --entrypoint id "$IMAGE"
```

## 4. Prima instalare

```bash
ROOT=/srv/apps/asistenta
sudo mkdir -p "$ROOT/data" "$ROOT/backups"
# proprietarul directorului data = uid 10001 (utilizatorul din container)
sudo chown -R 10001:10001 "$ROOT/data"

# fișiere de configurare (din pachet)
sudo cp deploy-docker/compose.yaml "$ROOT/compose.yaml"
sudo cp deploy-docker/.env.example "$ROOT/.env"
sudo cp deploy-docker/app.env.example "$ROOT/app.env"
sudo chmod 600 "$ROOT/.env" "$ROOT/app.env"
sudo chmod 700 "$ROOT/backups"

# editați $ROOT/.env: puneți APP_IMAGE=carpatica-asistenta:20261030-1 și
# verificați APP_DATA_DIR, APP_ENV_FILE, CADDY_NETWORK, APP_DOMAIN.
sudo nano "$ROOT/.env"
```

Validați și porniți (fără rebuild — imaginea e deja construită):

```bash
docker compose --env-file "$ROOT/.env" -f "$ROOT/compose.yaml" config --quiet
docker compose --env-file "$ROOT/.env" -f "$ROOT/compose.yaml" up -d --no-build
docker compose --env-file "$ROOT/.env" -f "$ROOT/compose.yaml" ps
```

Starea containerului trebuie să ajungă `healthy`:

```bash
cid=$(docker compose --env-file "$ROOT/.env" -f "$ROOT/compose.yaml" ps -q app)
docker inspect "$cid" --format '{{.State.Health.Status}}'
docker exec "$cid" python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3).read().decode())"
```

## 5. Site-ul Caddy

Adăugați blocul din `deploy-docker/Caddyfile.snippet` în Caddyfile-ul **comun**
(nu înlocuiți alte site-uri). Folosiți **Varianta A** (certificat public) dacă
laptopurile se conectează din orice rețea; **Varianta B** (`tls internal`) doar
pentru acces intern/VPN.

```bash
CADDYFILE=/srv/apps/proxy/Caddyfile          # calea reală din pasul 1
sudo cp "$CADDYFILE" "$CADDYFILE.bak.$(date +%Y%m%d%H%M%S)"   # backup
sudo nano "$CADDYFILE"                        # lipiți blocul asistenta.*

# validați în container înainte de activare
sudo cp "$CADDYFILE" /tmp/Caddyfile.candidate
docker cp /tmp/Caddyfile.candidate caddy:/tmp/Caddyfile.candidate
docker exec caddy caddy validate --config /tmp/Caddyfile.candidate --adapter caddyfile

# reîncărcați fără oprire
docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

> Dacă în container Caddyfile-ul e montat la altă cale decât `/etc/caddy/Caddyfile`,
> folosiți calea reală din `docker inspect caddy` (pasul 1).

## 6. Tehnician + token de înregistrare

Rulați în container (folosesc același `/data/config.json` și bază ca serverul):

```bash
cid=$(docker compose --env-file "$ROOT/.env" -f "$ROOT/compose.yaml" ps -q app)
docker exec -it "$cid" python -m server adduser adrian      # cere parola (min. 8)
docker exec "$cid" python -m server token                   # afișează ingest_token
```

`ingest_token` se pune în scriptul de pe laptopuri (dispozitive nesupravegheate /
RustDesk), acolo unde se raportează la `https://asistenta.carpaticaferoviar.ro/api/register`.

## 7. Verificare finală

```bash
# HTTPS + vhost + stare, păstrând domeniul și certificatul
curl.exe --resolve asistenta.carpaticaferoviar.ro:443:<IP_server> https://asistenta.carpaticaferoviar.ro/healthz   # PowerShell
# sau de oriunde, dacă DNS-ul public e deja setat:
curl -fsS https://asistenta.carpaticaferoviar.ro/healthz
```

Apoi un flux real: deschideți consola în browser, autentificați-vă cu tehnicianul
creat, și testați o conectare la un agent (ID + cod de acces).

## 8. Pointarea agenților

Agenții și dispozitivele folosesc domeniul (nu IP):

- Consolă: `https://asistenta.carpaticaferoviar.ro`
- Agent (asistență cu acord): `wss://asistenta.carpaticaferoviar.ro/ws/agent`
- Dispozitive nesupravegheate: `https://asistenta.carpaticaferoviar.ro/api/register`

În pachetul agentului, `config.json` → `server_url` = `wss://asistenta.carpaticaferoviar.ro/ws/agent`.
(Vezi `deploy-intune/` pentru propagarea prin Intune.)

## 9. Actualizarea la o versiune nouă

Construiți imaginea cu **tag nou** (pasul 3, ex. `20261030-2`), apoi:

```bash
ROOT=/srv/apps/asistenta
IMAGE=carpatica-asistenta:20261030-2
test ! -e "$ROOT/.env.next"
umask 077
sed "s|^APP_IMAGE=.*|APP_IMAGE=$IMAGE|" "$ROOT/.env" > "$ROOT/.env.next"
docker compose --env-file "$ROOT/.env.next" -f "$ROOT/compose.yaml" config --quiet
docker compose --env-file "$ROOT/.env.next" -f "$ROOT/compose.yaml" up -d --no-build --no-deps app

# așteptați „healthy”; dacă devine sănătos, activați definitiv:
cid=$(docker compose --env-file "$ROOT/.env.next" -f "$ROOT/compose.yaml" ps -q app)
docker inspect "$cid" --format '{{.State.Health.Status}}'
mv "$ROOT/.env.next" "$ROOT/.env"
```

**Rollback:** reporniți cu `.env`-ul vechi (imaginea anterioară):

```bash
docker compose --env-file "$ROOT/.env" -f "$ROOT/compose.yaml" up -d --no-build --no-deps app
```

Datele (`config.json` + SQLite) rămân în volum; secretele și tehnicienii se păstrează.

## 10. Backup

SQLite rulează în WAL — nu copiați fișierul `.db` în timp ce serverul scrie.
Faceți un snapshot coerent:

```bash
cid=$(docker compose --env-file "$ROOT/.env" -f "$ROOT/compose.yaml" ps -q app)
STAMP=$(date +%Y%m%d-%H%M%S)
docker exec "$cid" python -c "import sqlite3;sqlite3.connect('/data/asistenta.db').execute(\"VACUUM INTO '/data/backup-$STAMP.db'\")"
docker cp "$cid:/data/backup-$STAMP.db" "$ROOT/backups/backup-$STAMP.db"
docker exec "$cid" rm -f "/data/backup-$STAMP.db"
# păstrați și o copie a .env / app.env / blocului Caddy, cu acces restrâns.
```

Copiați periodic `backups/` pe NAS (criptat, cu retenție). Backupul + restartul
containerului **nu** înseamnă disponibilitate automată pe alt server.

---

### Diagnostic rapid (din retea-caddy.md)

| Simptom | De verificat |
| --- | --- |
| Timeout TCP 443 | rută/VPN/firewall/NAT, punctul de intrare al rețelei |
| Eroare certificat | numele cerut, CA, ora clientului; `tls internal` necesită root.crt pe client |
| `502` | alias `asistenta-app`, rețeaua `web`, portul 8080, backend `healthy`, ascultare pe `0.0.0.0` |
| `404 /healthz` | ruta aplicației și destinația proxy-ului (nu alt site) |
| `413` / upload | limite backend/proxy |

Nu colectați jurnale cu parole/tokenuri. Conectivitatea TCP singură nu dovedește
funcționarea platformei — verificați `/healthz` **și** un flux real.
