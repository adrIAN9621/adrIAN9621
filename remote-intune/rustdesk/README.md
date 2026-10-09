# Carpatica Remote – RustDesk cu acces nesupravegheat (Intune + manual)

Pachet de instalare pentru **RustDesk** în mod serviciu, cu acces nesupravegheat, pentru Carpatica Feroviar România SA. Înlocuiește Remote Help. RustDesk este open-source (AGPL-3.0), gratuit, fără licențe.

Pentru că serviciul rulează ca **SYSTEM**, accesul funcționează:
- **când se schimbă utilizatorii** (logout/login, alt user);
- **la ecranul de logon**, înainte să se conecteze cineva;
- **peste UAC** și ferestrele care cer drepturi de administrator.

## Fișiere
| Fișier | Rol |
|---|---|
| `config.ps1` | **Singurul fișier pe care îl editați.** Server, cheie, parolă, mod de acces. |
| `install.ps1` | Instalează RustDesk + serviciul, aplică serverul și parola, raportează ID-ul. |
| `uninstall.ps1` | Dezinstalează complet. |
| `detect.ps1` | Script de detecție pentru Intune. |
| `Instaleaza-Manual.bat` | Pentru laptopurile din afara Intune (Run as administrator). |

---

## Pasul 0 – Serverul RustDesk (o singură dată)
Pe un server Linux din rețeaua companiei, cu Docker:
```yaml
# compose.yml
services:
  hbbs:
    container_name: hbbs
    image: rustdesk/rustdesk-server:latest
    command: hbbs
    volumes: [ ./data:/root ]
    network_mode: "host"
    depends_on: [ hbbr ]
    restart: unless-stopped
  hbbr:
    container_name: hbbr
    image: rustdesk/rustdesk-server:latest
    command: hbbr
    volumes: [ ./data:/root ]
    network_mode: "host"
    restart: unless-stopped
```
```bash
docker compose up -d
```
Deschideți în firewall (doar intern / VPN): `21115/tcp`, `21116/tcp+udp`, `21117/tcp`.
După prima pornire, **cheia publică** e în `./data/id_ed25519.pub`. Copiați conținutul ei în `config.ps1` la `$RD_KEY`.

> Notă: portul web 21114 și consola sunt doar la RustDesk Server **Pro** (plătit). Pentru acces nesupravegheat **nu aveți nevoie de Pro** — varianta open-source e suficientă. Fără Pro nu există agendă centralizată, de aceea `install.ps1` raportează ID-ul + parola fiecărui laptop (vezi mai jos).

## Pasul 1 – Configurați pachetul
Editați `config.ps1`:
- `$RD_HOST` = gazda serverului (ex. `rustdesk.carpatica.local`);
- `$RD_KEY`  = cheia publică de mai sus;
- `$RD_PASSWORD` = lăsați `"random"` (recomandat: fiecare laptop are parola lui);
- `$RD_REPORT_URL` = opțional, un endpoint intern care primește `{id,password,hostname}` ca să colectați automat datele. Dacă e gol, datele rămân în `C:\ProgramData\CarpaticaRemote\device-info.txt` pe fiecare laptop.

## Pasul 2 – (Recomandat) puneți instalerul lângă scripturi
Descărcați instalerul RustDesk pentru Windows (`rustdesk-<versiune>-x86_64.exe`) de pe pagina oficială de release și salvați-l ca **`rustdesk.exe`** în acest folder. Astfel instalarea nu depinde de internet în momentul rulării. Dacă lipsește, `install.ps1` îl descarcă singur de pe GitHub (necesită acces la internet pe laptop).

---

## A. Laptopurile din afara Intune (acum)
Pe fiecare laptop: copiați folderul, click dreapta pe **`Instaleaza-Manual.bat` → Run as administrator**. La final afișează ID-ul și parola. Gata — laptopul e accesibil nesupravegheat.

## B. Împachetare pentru Intune (flota gestionată)
1. Descărcați **Microsoft Win32 Content Prep Tool** (`IntuneWinAppUtil.exe`).
2. Generați pachetul:
   ```
   IntuneWinAppUtil.exe -c <folderul_acesta> -s install.ps1 -o <folder_iesire>
   ```
   Rezultă `install.intunewin`.
3. În **Intune → Apps → Windows → Add → Windows app (Win32)**, încărcați `install.intunewin` și setați:
   - **Install command:**
     ```
     powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1
     ```
   - **Uninstall command:**
     ```
     powershell.exe -NoProfile -ExecutionPolicy Bypass -File uninstall.ps1
     ```
   - **Install behavior:** `System`
   - **Detection rules → Use a custom detection script:** încărcați `detect.ps1`.
   - **Requirements:** Windows 10/11, x64.
4. Alocați aplicația grupului de laptopuri (Required). Intune o instalează tăcut, ca SYSTEM.

### Colectarea ID-urilor și parolelor
- Cu `$RD_REPORT_URL` setat: datele vin automat la endpoint-ul vostru.
- Fără el: ID-ul + parola sunt în `C:\ProgramData\CarpaticaRemote\device-info.txt`. Le puteți aduna cu un script de inventar sau cu un Proactive Remediation în Intune care citește fișierul.

---

## Conectare de la tehnician
1. Instalați clientul RustDesk pe PC-ul tehnicianului și, în **Settings → Network**, puneți aceeași gazdă și cheie (`$RD_HOST`, `$RD_KEY`).
2. Introduceți ID-ul laptopului și parola lui. Vă conectați fără ca cineva să fie la laptop.

## Securitate (obligatoriu de respectat)
- Parole **per-laptop** (`random`), nu una comună.
- Portul serverului doar în rețeaua internă sau prin VPN.
- `device-info.txt` conține parola în clar: tratați-l ca date sensibile; preferați `$RD_REPORT_URL` către un sistem cu acces restrâns.
- Informați angajații, în scris, că stațiile pot fi accesate de IT pentru mentenanță (cerință GDPR / Codul muncii). RustDesk arată un indicator de conexiune pe durata sesiunii — nu îl dezactivați.

## Limitări / de verificat
- Scripturile folosesc opțiunile RustDesk (`--option custom-rendezvous-server/key/relay-server`, `--password`, `--get-id`). Pe versiuni foarte noi, numele unor opțiuni se pot schimba; **testați întâi pe 1–2 laptopuri** și confirmați din clientul tehnicianului că apar conectate la serverul vostru.
- Dacă folosiți RustDesk Server **Pro**, puteți livra un „config string” unic (Settings → Network → Export) și îl puteți aplica cu `rustdesk.exe --config <string>` în loc de cele trei `--option`.
- Nu am putut testa scripturile pe Windows din acest mediu; sunt scrise după documentația oficială și trebuie probate pe o stație reală înainte de rulout.
