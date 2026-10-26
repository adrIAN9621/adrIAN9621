# Server online pe Linux + Cloudflare Tunnel

Serverul rulează pe serverul tău Linux (ascultă doar local), iar Cloudflare îl publică
la `asistenta.carpaticaferoviar.ro` cu **TLS automat**. Toate laptopurile se conectează
la acea adresă, din orice rețea.

## 1. Serverul ca serviciu
Pe serverul Linux, în folderul `it-asistenta`:
```bash
sudo apt install -y python3 python3-venv     # daca lipsesc
sudo bash deploy-linux/install-server.sh
```
Scriptul: face venv, instalează dependențele, pune config pe `127.0.0.1:8443`
(`allow_insecure` — TLS îl pune Cloudflare în față), creează un tehnician, instalează
serviciul `carpatica-asistenta` (pornește singur la boot) și afișează tokenul de
înregistrare a laptopurilor.

Verificare: `curl -s http://127.0.0.1:8443/__alive` → `{"app":"pdf-studio"}` ... (ok, răspunde).

## 2. Cloudflare Tunnel
Domeniul `carpaticaferoviar.ro` e deja pe Cloudflare. Pe serverul Linux:
```bash
# instaleaza cloudflared (vezi pkg.cloudflare.com / GitHub cloudflare/cloudflared)
cloudflared tunnel login                       # autentificare (o data)
cloudflared tunnel create carpatica-asistenta
cloudflared tunnel route dns carpatica-asistenta asistenta.carpaticaferoviar.ro
```
Config `/etc/cloudflared/config.yml`:
```yaml
tunnel: carpatica-asistenta
credentials-file: /root/.cloudflared/<ID-TUNEL>.json
ingress:
  - hostname: asistenta.carpaticaferoviar.ro
    service: http://127.0.0.1:8443
  - service: http_status:404
```
Rulează ca serviciu:
```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

## 3. Gata — adresele publice
- **Consola tehnicieni:** `https://asistenta.carpaticaferoviar.ro`
- **Agenți (în config.json / deploy-intune):** `wss://asistenta.carpaticaferoviar.ro/ws/agent`
- **Dispozitive RustDesk (raportare):** `https://asistenta.carpaticaferoviar.ro/api/register`

Toate merg **din orice rețea**, criptat (TLS Cloudflare) — fără firewall/izolare de LAN.

## Test rapid (fără a aștepta DNS)
`cloudflared tunnel --url http://127.0.0.1:8443` → URL temporar `https://....trycloudflare.com`.

## Securitate (NIS2)
- Nu mai folosi `allow_insecure` în afară de legătura locală cloudflared↔server (127.0.0.1).
  Spre exterior totul e HTTPS/WSS prin Cloudflare.
- Pune **MFA** pentru tehnicieni (pot adăuga TOTP în server) și, în Cloudflare, poți pune
  **Cloudflare Access** (autentificare în plus pe consolă).
