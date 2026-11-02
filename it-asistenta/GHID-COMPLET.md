# Carpatica Asistență IT — Ghid complet

Aplicație internă de **asistență la distanță cu acordul angajatului** (gen AnyDesk/TeamViewer, dar a firmei, pe serverul nostru). Tehnicianul IT se conectează la calculatorul unui coleg **doar după ce acesta acceptă**, vede ecranul și poate prelua mouse/tastatură pentru a ajuta.

> Uz intern Carpatica Feroviar România. Nicio dată nu pleacă în afara infrastructurii proprii.

---

## 1. Din ce e făcută (arhitectură)

Trei componente:

| Componentă | Unde rulează | Rol |
|---|---|---|
| **Server** | `appsrv1` (172.17.17.115), în Docker | „Centrala" — leagă tehnicianul de calculatorul asistat |
| **Consola** | în browser, `https://asistenta.carpaticaferoviar.ro` | Panoul tehnicianului: listă calculatoare, conectare, ecran live |
| **Agentul** | pe calculatorul angajatului (`Carpatica-Asistenta-IT.exe`) | Afișează ID + cod, cere acordul, trimite ecranul |

**Important — model cu server la mijloc:** nimeni nu se conectează direct la rețeaua celuilalt. Atât agentul, cât și tehnicianul **ies** spre server, iar serverul îi leagă:

```
Calculator angajat (agent) ──►  SERVER asistenta  ◄── Tehnician (consolă)
```

---

## 2. Cum decurge o asistență (flux)

1. Angajatul pornește **Carpatica-Asistenta-IT.exe** (iconiță pe desktop). Apare o fereastră cu un **ID** (9 cifre) și un **cod de acces** (6 cifre).
2. Angajatul îi comunică tehnicianului **ID-ul + codul** (telefon, chat etc.).
3. Tehnicianul deschide consola → tab **Calculatoare** → introduce ID-ul + codul → **Conectare**.
4. Pe calculatorul angajatului apare o cerere de confirmare → angajatul apasă **Accept**.
5. Tehnicianul **vede ecranul** și poate prelua controlul. La final, apasă **Încheie sesiunea**.

Fără pasul 4 (Accept) nu există conexiune — angajatul controlează mereu accesul.

---

## 3. Pentru tehnician — folosirea consolei

- **Adresă:** `https://asistenta.carpaticaferoviar.ro`
- **Autentificare:** utilizator + parolă (cont IT, creat de administrator).
- **Tab „Calculatoare":** aici lucrezi — vezi calculatoarele online și te conectezi cu ID + cod.
- **Tab „Dispozitive":** neutilizat la noi (e pentru acces nesupravegheat; îl poți ignora).

În timpul sesiunii ai: alegere monitor, calitate imagine, mărime reală, trimite text/clipboard, chat cu angajatul, ecran complet.

---

## 4. Instalarea agentului pe un calculator

### Ce fișiere trebuie (2)
Dintr-un folder, copiate **împreună**:
- `Carpatica-Asistenta-IT.exe`
- `config.json`

> Cele două trebuie să fie în **același folder** — agentul citește `config.json` de lângă el.

### Pași (test manual pe un calculator)
1. Copiezi cele 2 fișiere într-un folder pe calculator (ex. pe Desktop).
2. Dublu-click pe `Carpatica-Asistenta-IT.exe`.
3. Apare fereastra cu **ID + cod**. Dacă scrie **„Conectat la server"** jos → e gata de folosit.

### Instalare „ca la carte" (cu iconiță pe desktop)
Folosește pachetul din `deploy-intune\` (pentru Intune sau manual):
- Click dreapta pe `install.cmd` → **Run as administrator**.
- Copiază aplicația în `C:\Program Files\Carpatica Asistenta IT\`, pune **iconiță pe Desktop** (fără pornire automată — o deschide userul când are nevoie).
- Dezinstalare: `uninstall.cmd` (Run as administrator).

### Propagare pe toată flota
Prin **Microsoft Intune**, ca aplicație Win32 (pachet `.intunewin` din `deploy-intune\`). Vezi `deploy-intune\README.md`.

---

## 5. Condiții ca să funcționeze pe un calculator

Agentul se conectează la `wss://asistenta.carpaticaferoviar.ro/ws/agent`. Deci calculatorul trebuie:

1. **Să rezolve numele** `asistenta.carpaticaferoviar.ro → 172.17.17.115`.
   - **Corect (toți):** 1 record în **UniFi → Local DNS Records** (ca `inventariere`). Atunci toate calculatoarele îl rezolvă automat, nu atingi niciunul.
   - **Temporar (1 calculator, test):** linie în `hosts` (PowerShell Administrator):
     ```powershell
     Add-Content "$env:windir\System32\drivers\etc\hosts" "172.17.17.115`tasistenta.carpaticaferoviar.ro"
     ipconfig /flushdns
     ```
2. **Să fie pe rețeaua Carpatica sau pe VPN** (WireGuard) care ajunge la `172.17.17.115`. De acasă → trebuie VPN pornit.
3. **Certificat** — serverul folosește o autoritate internă (`tls internal`):
   - Pentru conexiune **sigură**: calculatorul are `caddy-root.crt` în *Trusted Root* (ca la celelalte site-uri interne), iar în `config.json` → `"verify_tls": true`.
   - Pentru **test rapid** (nesigur): `"verify_tls": false` în `config.json` (sare peste verificare). A nu se lăsa așa pe flotă.

---

## 6. `config.json` — exemplu

```json
{
  "server_url": "wss://asistenta.carpaticaferoviar.ro/ws/agent",
  "verify_tls": true,
  "ca_file": "caddy-root.crt",
  "default_quality": 60,
  "default_scale": 1.0,
  "default_fps": 10
}
```
- `server_url` — adresa serverului (nu se schimbă).
- `verify_tls` — `true` în producție (sigur), `false` doar la test.
- `ca_file` — fișierul CA intern, pus **lângă** `.exe` (dacă folosești verificarea cu CA din fișier).

> **Atenție la editare:** salvează `config.json` **fără BOM**. Cu Notepad e ok; dacă îl faci din PowerShell, folosește `[System.IO.File]::WriteAllText(...)`, nu `Set-Content -Encoding utf8` (acela adaugă un BOM care strică citirea).

---

## 7. Server & administrare (sumar)

Serverul rulează în Docker pe `appsrv1`, în spatele proxy-ului comun Caddy. Pachetul și pașii compleți: `deploy-docker\README.md`.

Comenzi utile (pe server, prin SSH):
```bash
ROOT=/srv/apps/asistenta
cid=$(docker compose --env-file "$ROOT/.env" -f "$ROOT/compose.yaml" ps -q app)

# adaugă un tehnician (cere parolă)
docker exec -it "$cid" python -m server adduser <nume>

# stare container
docker inspect "$cid" --format '{{.State.Health.Status}}'

# jurnal
docker compose --env-file "$ROOT/.env" -f "$ROOT/compose.yaml" logs --tail=50 app
```

Actualizare la o versiune nouă: rebuild imagine cu tag nou + `up -d` (vezi `deploy-docker\README.md`, secțiunea Actualizare).

---

## 8. Depanare (probleme reale și soluții)

| Simptom | Cauză | Soluție |
|---|---|---|
| Agentul: **„Se reconectează…"** la nesfârșit | Nu găsește `config.json` lângă `.exe` sau fișierul are **BOM** → folosește adresă greșită | `config.json` lângă `.exe`, salvat fără BOM, cu `server_url` corect |
| **ERR_QUIC_PROTOCOL_ERROR** în browser | Bug QUIC/HTTP3 în Brave | `brave://flags/#enable-quic` → **Disabled** → Relaunch; sau Edge |
| **This site can't be reached** / DNS | Numele nu se rezolvă | Record în UniFi, sau linie în `hosts`; `ipconfig /flushdns` |
| **TcpTestSucceeded: False** / „General failure" la ping | Nu ești pe rețea/VPN care ajunge la `172.17.17.115`, sau **2 VPN-uri** active care se bat cap în cap | Pornește **un singur** VPN corect (WireGuard) spre `172.17.17.0/24` |
| Avertisment de certificat | CA-ul intern nu e instalat pe calculator | Instalează `caddy-root.crt` în *Trusted Root*; sau `verify_tls:false` la test |
| **„Utilizator sau parolă incorectă"** | Nume de utilizator greșit (ține cont de litere mici) | Scrie exact userul (ex. `adrian`, nu `Adrian`) |

Verificare rapidă a conectivității (PowerShell):
```powershell
Test-NetConnection asistenta.carpaticaferoviar.ro -Port 443   # TcpTestSucceeded trebuie True
```

---

## 9. Securitate

- Conexiunea e **criptată (TLS)** și consola cere **autentificare**.
- Accesul la ecranul angajatului se face **doar cu acordul lui** (Accept).
- Toate acțiunile sunt **înregistrate** (jurnal de audit pe server).
- Serverul e **intern** (accesibil din rețea sau prin VPN) — nu e expus pe internet.
- În producție se folosește `verify_tls:true` (certificat verificat); `verify_tls:false` e doar pentru teste.

---

## 10. Adrese utile

| | Adresă |
|---|---|
| Consolă (tehnician) | `https://asistenta.carpaticaferoviar.ro` |
| Server (IP intern) | `172.17.17.115` |
| Endpoint agent | `wss://asistenta.carpaticaferoviar.ro/ws/agent` |

Pachete și documentație în repo (`it-asistenta/`):
- `deploy-docker/` — instalarea serverului (Docker + Caddy)
- `deploy-intune/` — propagarea agentului prin Intune (+ iconiță desktop)
- `deploy-cloudflared/` — (opțional) acces din afara rețelei fără VPN
- `agent/` — sursa agentului și `build_exe.bat`
