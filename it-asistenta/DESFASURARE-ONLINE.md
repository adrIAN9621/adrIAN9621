# Server online — conectare la laptopuri indiferent de rețea/IP

Problema cu „serverul pe un laptop în LAN": merge doar în acea rețea; rețelele de
firmă izolează dispozitivele, iar laptopurile din alte birouri / de acasă / pe VPN
nu-l pot atinge. Soluția: serverul să aibă o **adresă publică** la care TOATE
laptopurile se conectează spre exterior (ca AnyDesk/RustDesk). Trei variante.

---

## Varianta 1 (recomandată) — Cloudflare Tunnel (GRATUIT, TLS, fără VPS)
Serverul rulează pe o mașină internă mereu pornită (un server mic, un mini-PC, chiar
un laptop dedicat). `cloudflared` îl expune la un **nume public cu HTTPS/WSS automat**,
fără IP public, fără port-forwarding, fără deschideri de firewall spre exterior.

Cerință: domeniul vostru (**carpaticaferoviar.ro**) să fie pe Cloudflare (plan gratuit).

Pași:
1. Pui DNS-ul domeniului pe Cloudflare (gratis) — o singură dată.
2. Pe mașina cu serverul:
   - pornești serverul: `py -3 -m server run --host 127.0.0.1` (doar local; tunelul îl publică);
   - instalezi **cloudflared**, te loghezi (`cloudflared login`), creezi tunelul:
     ```
     cloudflared tunnel create carpatica-asistenta
     cloudflared tunnel route dns carpatica-asistenta asistenta.carpaticaferoviar.ro
     ```
   - config `~/.cloudflared/config.yml`:
     ```yaml
     tunnel: carpatica-asistenta
     credentials-file: C:\Users\...\.cloudflared\<id>.json
     ingress:
       - hostname: asistenta.carpaticaferoviar.ro
         service: http://127.0.0.1:8443
       - service: http_status:404
     ```
   - rulezi tunelul ca serviciu: `cloudflared service install`
3. **Toți agenții** folosesc: `wss://asistenta.carpaticaferoviar.ro/ws/agent`
   Consola: `https://asistenta.carpaticaferoviar.ro`
4. TLS e automat (Cloudflare) → criptat (bun pentru NIS2). Nu mai pui `allow_insecure`.

Pentru un TEST rapid, fără domeniu: `cloudflared tunnel --url http://127.0.0.1:8443`
îți dă un URL aleator `https://....trycloudflare.com` (bun doar de probă).

---

## Varianta 2 — VPS în cloud (control total, ~4-5 €/lună)
Un server mic (Hetzner, DigitalOcean, Contabo) cu IP public + domeniu + TLS Let's Encrypt.
1. Închiriezi un VPS Linux mic.
2. Pui serverul (Python) + `python -m server gencert` sau Let's Encrypt (Caddy/nginx în față).
3. Deschizi portul 8443 (sau 443) în firewall-ul VPS-ului.
4. Agenții: `wss://asistenta.carpaticaferoviar.ro/ws/agent`.
Avantaj: nimic în rețeaua firmei, merge de oriunde, control complet.

---

## Varianta 3 — server intern cu IP fix + port-forward (doar dacă e nevoie)
Dacă laptopurile sunt mereu pe rețeaua firmei: pui serverul pe un server intern cu IP
fix la care rețeaua PERMITE acces de la toate laptopurile. Pentru acces de acasă/VPN ar
trebui port-forwarding pe routerul firmei + DNS dinamic — depinde de IT-ul de rețea și e
mai puțin curat decât variantele 1-2.

---

## Recomandarea
- Cel mai bun raport simplu/sigur/gratuit: **Cloudflare Tunnel** (Varianta 1) pe un
  mini-PC/server intern. TLS inclus, merge de oriunde, fără a expune rețeaua firmei.
- Dacă vrei independență totală de infrastructura firmei: **VPS** (Varianta 2).

În ambele, pui în agent un singur `server_url` cu numele public (`wss://...`) — și de
atunci **orice laptop, din orice rețea, se conectează**.
