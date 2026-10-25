# Carpatica Asistență IT – INSTALATOR UNIC (RustDesk + agent „cu acord")

Un **singur pachet** care pune pe un laptop **ambele** moduri de asistență la distanță și le leagă de **serverul unificat** Carpatica Asistență IT:

1. **RustDesk** în mod serviciu, cu **acces nesupravegheat** (IT se conectează cu ID + parolă, fără ca cineva să fie la laptop). ID-ul și parola sunt raportate automat la server.
2. **Agentul „cu acord"** (`Carpatica-Asistenta-IT.exe`) – aplicația cu interfață care cere acordul angajatului și se conectează prin WebSocket la server.

Acest folder **reutilizează** scripturile existente din `..\rustdesk` (nu le modifică) și scrie config-ul agentului din `..\..\it-asistenta\agent`.

---

## Fișiere din pachet
| Fișier | Rol |
|---|---|
| `config.ps1` | **Singurul fișier pe care îl editați.** Server unificat, ingest_token, RD_HOST/RD_KEY etc. |
| `Install-RemoteCarpatica.ps1` | Instalează RustDesk (serviciu + raportare la `/api/register`) **și** agentul. |
| `Instaleaza-Remote-Carpatica.bat` | Dublu-click → „Run as administrator" (instalare manuală). |
| `Uninstall-RemoteCarpatica.ps1` | Dezinstalează ambele componente. |
| `remediation/Detect-RemoteCarpatica.ps1` | Intune Remediations – verifică periodic ambele componente. |
| `remediation/Remediate-RemoteCarpatica.ps1` | Intune Remediations – re-raportează + repornește ce e oprit. |
| `Carpatica-Asistenta-IT.exe` | **Îl puneți voi** (construit cu `build_exe.bat`, vezi mai jos). |
| `rustdesk.exe` *(opțional)* | Instalerul RustDesk bundelat (altfel se descarcă de pe GitHub). |

---

## Pasul 1 – Tokenul de înregistrare (ingest_token)
Pe **serverul unificat**, rulați:
```
python -m server token
```
Copiați valoarea afișată în `config.ps1`, la `$INGEST_TOKEN`. Cu acest token laptopul raportează ID-ul + parola RustDesk la `POST /api/register`.

> Dacă apare `(negenerat — porniți serverul o dată)`, porniți serverul o dată (`python -m server run`) și reluați comanda.

## Pasul 2 – Construiți executabilul agentului
Pe o mașină Windows cu Python 3.10+:
```
cd it-asistenta\agent
build_exe.bat
```
Rezultă `it-asistenta\agent\dist\Carpatica-Asistenta-IT.exe`. **Copiați-l** în acest folder (`remote-intune\unificat\`), lângă `Install-RemoteCarpatica.ps1`.

> `config.json` este oricum rescris de instalator pe fiecare laptop (cu `server_url` corect), deci nu contează ce config a fost inclus în `.exe` la build.

## Pasul 3 – Editați `config.ps1`
Completați cel puțin:
- `$SERVER_URL` – ex. `https://server.carpatica:8443` (din el se derivă automat `/api/register` și `wss://.../ws/agent`).
- `$INGEST_TOKEN` – de la Pasul 1.
- `$RD_HOST` și `$RD_KEY` – gazda și cheia publică a serverului vostru RustDesk.

## Pasul 4 – Testare manuală pe un laptop
1. Copiați folderul `unificat\` (cu `.exe`-ul agentului înăuntru) pe laptop.
2. Click dreapta pe `Instaleaza-Remote-Carpatica.bat` → **Run as administrator**.
3. La final vedeți ID-ul + parola RustDesk (din `C:\ProgramData\CarpaticaRemote\device-info.txt`).
4. Verificați în consola serverului că laptopul apare (RustDesk raportat) și că agentul „cu acord" pornește după re-logare (scurtătură în Startup).

Jurnale utile pe laptop:
- `C:\ProgramData\CarpaticaRemote\install-unificat.log` (pachetul unificat)
- `C:\ProgramData\CarpaticaRemote\install.log` (partea RustDesk)

---

## Punere în Intune

### A) Aplicație Win32 (`.intunewin`) – instalarea de bază
1. Puneți în acest folder: `Carpatica-Asistenta-IT.exe`, `config.ps1` editat și, opțional, `rustdesk.exe`. Lângă folder trebuie să existe și `..\rustdesk\install.ps1` (păstrați structura de directoare `remote-intune\rustdesk` + `remote-intune\unificat`), sau rulați instalatorul cu `-RustDeskDir <cale>`.
2. Împachetați cu **Microsoft Win32 Content Prep Tool** folderul `unificat`.
3. În Intune:
   - **Install command:**
     ```
     powershell.exe -NoProfile -ExecutionPolicy Bypass -File Install-RemoteCarpatica.ps1
     ```
   - **Uninstall command:**
     ```
     powershell.exe -NoProfile -ExecutionPolicy Bypass -File Uninstall-RemoteCarpatica.ps1
     ```
   - **Install behavior:** System.
   - **Detection rule:** fișier existent `C:\Program Files\Carpatica Asistenta IT\Carpatica-Asistenta-IT.exe` **și/sau** `C:\Program Files\RustDesk\rustdesk.exe` (sau folosiți un script de detecție propriu).

> Pachetul Win32 trebuie să includă și `..\rustdesk` sau să pasați `-RustDeskDir`. Cel mai simplu: împachetați `remote-intune` întreg și setați folderul de start `unificat`.

### B) Intune Remediations – verificare periodică
În **Devices → Remediations → Create**:
- **Detection script:** `remediation/Detect-RemoteCarpatica.ps1`
- **Remediation script:** `remediation/Remediate-RemoteCarpatica.ps1`
- **Run this script using the logged-on credentials:** No (rulează ca SYSTEM).
- **Enforce script signature check:** după politica voastră.

Înainte de încărcare, editați **antetul** din `Remediate-RemoteCarpatica.ps1` (și numele din `Detect-RemoteCarpatica.ps1`) ca să corespundă cu `config.ps1`:
`$REGISTER_URL`, `$INGEST_TOKEN`, `$AGENT_PRODUCT`, `$AGENT_EXE_NAME`.

> Scripturile Intune Remediations se încarcă fiecare ca **fișier unic**, deci nu pot citi `config.ps1`; de aceea valorile sunt copiate în antetul lor. Parola nu ajunge niciodată în portalul Intune – doar ID-ul și hostname-ul apar la STDOUT.

---

## Ce reutilizează (nemodificat) din pachetele existente
- `..\rustdesk\install.ps1` – instalarea RustDesk + serviciu + **raportarea** ID/parolă (instalatorul unific îl rulează dintr-o copie temporară, configurat să raporteze la `/api/register`).
- `..\rustdesk\uninstall.ps1` – dezinstalarea RustDesk.
- Logica de raportare din `..\rustdesk\remediation\Remediate-ReportDeviceInfo.ps1` – adaptată în `remediation/Remediate-RemoteCarpatica.ps1` pentru `/api/register`.
- `..\..\it-asistenta\agent\build_exe.bat` – construiește `.exe`-ul agentului.

## Dezinstalare manuală
Click dreapta pe PowerShell → Run as administrator:
```
powershell -NoProfile -ExecutionPolicy Bypass -File Uninstall-RemoteCarpatica.ps1
```
