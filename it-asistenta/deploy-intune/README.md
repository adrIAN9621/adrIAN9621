# Agentul Carpatica Asistență IT ca aplicație Intune (Win32)

Împachetezi agentul ca `.intunewin` și îl împingi pe toate laptopurile din Intune.
Agentul e un `.exe` de sine stătător (nu cere Python pe laptop).

## 0. Cerință
Serverul trebuie să aibă deja o adresă publică (vezi `../DESFASURARE-ONLINE.md`),
ex. `wss://asistenta.carpaticaferoviar.ro/ws/agent`.

## 1. Construiește `.exe`-ul (o singură dată, pe un Windows cu Python)
```
cd it-asistenta\agent
build_exe.bat
```
→ rezultă `it-asistenta\agent\dist\Carpatica-Asistenta-IT.exe`.
Copiază acel `.exe` în folderul **`deploy-intune\`** (lângă `install.cmd`).

## 2. Pune adresa serverului
Editează **`deploy-intune\config.json`** → `server_url` = adresa publică a serverului
(`wss://asistenta.carpaticaferoviar.ro/ws/agent`). Lași `verify_tls: true`
(Cloudflare are certificat valid).

## 3. Creează pachetul `.intunewin`
Descarcă **Microsoft Win32 Content Prep Tool** (`IntuneWinAppUtil.exe`) de pe GitHub
(microsoft/Microsoft-Win32-Content-Prep-Tool). Apoi:
```
IntuneWinAppUtil.exe -c deploy-intune -s install.cmd -o output
```
→ rezultă `output\install.intunewin`.

## 4. Adaugă aplicația în Intune
Intune → **Apps → Windows → Add → Windows app (Win32)** → încarcă `install.intunewin`.
- **Install command:**   `install.cmd`
- **Uninstall command:** `uninstall.cmd`
- **Install behavior:**  **System**
- **Detection rule:** *Use a custom detection script* → încarcă `detect.ps1`
  (sau regulă de fișier: există `%ProgramFiles%\Carpatica Asistenta IT\Carpatica-Asistenta-IT.exe`).
- **Assignments:** atribuie la un grup de dispozitive (ex. toate laptopurile).

## Ce face pe laptop
- Copiază `.exe` + `config.json` în `C:\Program Files\Carpatica Asistenta IT\`.
- Pune o **iconiță pe Desktop** (toți utilizatorii) + scurtătură în meniul Start.
  **Fără autorulare** — userul pornește agentul manual, de pe iconiță, când are nevoie de suport.
- Agentul rulează în sesiunea utilizatorului și afișează o fereastră cu **ID + cod**
  (ca AnyDesk). Starea (ID+secret) se salvează în `%APPDATA%\CarpaticaAsistentaIT`.
- Tehnicianul se conectează din consolă cu ID-ul + codul; angajatul **acceptă**.

## Note
- Dacă vrei ca agentul să pornească **minimizat/în tray** (fără fereastră la logon),
  pot adăuga acest mod în agent — spune-mi.
- La actualizarea agentului: reconstruiești `.exe`-ul, refaci `.intunewin`, crești
  versiunea aplicației în Intune → se actualizează pe toate.
- RustDesk (nesupravegheat) se instalează separat prin `remote-intune/` — cele două
  moduri se completează (vezi panoul unificat, tab-urile Asistență / Dispozitive).
