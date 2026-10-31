# Acces din afara rețelei – Cloudflare Tunnel

Publică `https://asistenta.carpaticaferoviar.ro` pe internet, ca **tehnicianul de
acasă** și **laptopurile din orice rețea** să ajungă la server — fără porturi
deschise în firewall și cu **certificat public** (nu mai trebuie CA-ul intern pe
laptopurile externe).

```
Laptop/consolă de oriunde  →  Cloudflare (HTTPS public)  →  tunel  →  cloudflared pe appsrv1  →  asistenta-app:8080
```

Nu atinge Caddy sau celelalte aplicații. `cloudflared` rulează pe rețeaua `web`
și vorbește direct cu containerul aplicației prin aliasul `asistenta-app`.

---

## 1. Creează tunelul în Cloudflare
1. Cloudflare dashboard → **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel**.
2. Tip: **Cloudflared**. Nume: `carpatica-asistenta`. **Save**.
3. La „Choose your environment" alege **Docker**. Se afișează o comandă cu un
   **token** lung (`eyJ...`). Copiază **doar tokenul** (partea de după `--token`).
   Notează și versiunea imaginii din comandă (ex. `cloudflare/cloudflared:2024.x.x`).

## 2. Pornește cloudflared pe appsrv1
```bash
ROOT=/srv/apps/cloudflared
sudo mkdir -p "$ROOT"
sudo cp ~/adrian/it-asistenta/deploy-cloudflared/compose.yaml "$ROOT/compose.yaml"
sudo cp ~/adrian/it-asistenta/deploy-cloudflared/.env.example  "$ROOT/.env"
sudo chown "$USER":"$USER" "$ROOT/.env" "$ROOT/compose.yaml"
sudo chmod 600 "$ROOT/.env"
# pune tokenul in .env (inlocuieste textul de exemplu):
nano "$ROOT/.env"
```
Dacă versiunea imaginii din dashboard diferă, actualizeaz-o în `compose.yaml`
(linia `image:`). Apoi:
```bash
docker compose --env-file "$ROOT/.env" -f "$ROOT/compose.yaml" up -d
docker compose --env-file "$ROOT/.env" -f "$ROOT/compose.yaml" logs --tail=20
```
În dashboard, tunelul trebuie să apară **HEALTHY** (conexiune stabilită).

## 3. Rutează domeniul spre aplicație
În pagina tunelului → **Public Hostname** → **Add a public hostname**:
- **Subdomain:** `asistenta`
- **Domain:** `carpaticaferoviar.ro`
- **Type:** `HTTP`
- **URL:** `asistenta-app:8080`

**Save**. Cloudflare creează automat înregistrarea DNS și certificatul public.
WebSocket-ul (`/ws/agent`) e suportat automat — nu trebuie nimic în plus.

## 4. Verifică
De pe orice conexiune (inclusiv mobil, în afara rețelei):
```
https://asistenta.carpaticaferoviar.ro/healthz
```
→ `{"status":"ok","app":"asistenta"}` cu **lacăt verde** (certificat public, fără avertisment).

Apoi deschide consola și loghează-te; agentul de pe un laptop extern ar trebui
să se conecteze la `wss://asistenta.carpaticaferoviar.ro/ws/agent`.

---

## Important după activare
- **Scoate linia din `hosts`** de pe laptopurile de test (cea cu `172.17.17.115
  asistenta.carpaticaferoviar.ro`). Altfel acel laptop merge pe calea internă
  (Caddy, cert intern) în loc de Cloudflare (cert public). După ștergere:
  `ipconfig /flushdns`.
- Agentul merge cu `verify_tls: true` fără CA, pentru că certificatul Cloudflare
  e public — exact ce avem deja în `config.json`.

## (Recomandat) Protejează consola cu Cloudflare Access
Consola devine publică; login-ul aplicației o apără, dar un strat suplimentar e
indicat. În **Zero Trust → Access → Applications → Add → Self-hosted**:
- **Application domain:** `asistenta.carpaticaferoviar.ro`
- **Policy:** permite doar emailuri `@carpaticaferoviar.ro` (sau persoane anume).
- **IMPORTANT – lasă agenții să treacă:** adaugă o aplicație Access separată sau
  reguli de **Bypass** pentru căile folosite de agenți, altfel se blochează:
  - `asistenta.carpaticaferoviar.ro/ws/agent`
  - `asistenta.carpaticaferoviar.ro/api/register`
  - `asistenta.carpaticaferoviar.ro/healthz`
  Restul (consola `/`, `/api/login`, `/api/...`) rămâne în spatele Access.

> Dacă pui Access pe tot domeniul fără bypass, agenții nu se mai pot conecta
> (nu pot face login interactiv Cloudflare). De aceea bypass-ul pe `/ws/agent`
> și `/api/register` e obligatoriu.

## Oprire
```bash
docker compose --env-file /srv/apps/cloudflared/.env -f /srv/apps/cloudflared/compose.yaml down
```
(Serverul aplicației rămâne; doar accesul public prin tunel se oprește.)
