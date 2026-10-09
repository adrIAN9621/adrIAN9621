# Plan de testare cu 3 laptopuri (acasă, fără serverul companiei)

Testezi fluxul complet, exact ca în producție — doar că „serverul companiei” e unul dintre laptopurile tale. Nimic în cloud, nimic de la companie.

## Rolurile
| Laptop | Rol | Ce rulează |
|---|---|---|
| **A** | „Serverul” | Serverul RustDesk (hbbs/hbbr) + colectorul |
| **B** | Angajatul (ținta) | Agentul RustDesk ca serviciu |
| **C** | Tehnicianul | Clientul RustDesk |

Toate în **aceeași rețea Wi-Fi/LAN**.

---

## Pasul 1 — Laptop A: aflați IP-ul și porniți serverul

1. **IP-ul lui A:** deschideți `cmd` → `ipconfig` → notați „IPv4 Address” (ex. `192.168.1.10`). Îl vom numi `IP_A`.

2. **Serverul RustDesk** (fără Docker, cu binarele oficiale pentru Windows):
   - Descărcați „RustDesk Server” pentru Windows de pe pagina oficială de release (`rustdesk-server-windows-x86_64.zip`), dezarhivați.
   - Deschideți două ferestre `cmd` în folderul dezarhivat și rulați:
     ```
     hbbs.exe
     ```
     ```
     hbbr.exe
     ```
   - La prima pornire se creează fișierul `id_ed25519.pub` în același folder. **Deschideți-l și copiați conținutul** (o linie). Aceasta e `CHEIA`.

3. **Firewall pe A:** permiteți porturile `21115`, `21116` (TCP+UDP), `21117`, și `8070` (colector). Rapid, din `cmd` ca administrator:
   ```
   netsh advfirewall firewall add rule name="RustDesk" dir=in action=allow protocol=TCP localport=21115-21119
   netsh advfirewall firewall add rule name="RustDeskUDP" dir=in action=allow protocol=UDP localport=21116
   netsh advfirewall firewall add rule name="Colector" dir=in action=allow protocol=TCP localport=8070
   ```

4. **Colectorul pe A:**
   ```
   cd remote-intune\collector
   pip install -r requirements.txt
   python -m collector init
   ```
   Deschideți `config.json` și puneți `"allow_insecure": true` (doar pentru test local). Notați `ingest_token` din el. Apoi:
   ```
   python -m collector adduser test
   python -m collector
   ```
   Verificați în browser pe A: `http://127.0.0.1:8070` (user „test”).

---

## Pasul 2 — Laptop B: instalați agentul (ținta)

1. Copiați folderul `remote-intune\rustdesk` pe B.
2. Editați `config.ps1`:
   ```powershell
   $RD_HOST         = "IP_A"          # ex. 192.168.1.10
   $RD_KEY          = "CHEIA"         # conținutul id_ed25519.pub de pe A
   $RD_RELAY        = "IP_A"
   $RD_PASSWORD     = "random"
   $RD_REPORT_URL   = "http://IP_A:8070/api/register"
   $RD_REPORT_TOKEN = "ingest_token-ul de pe A"
   ```
3. Click dreapta pe `Instaleaza-Manual.bat` → **Run as administrator**.
4. La final vă arată ID-ul și parola. Pe A, reîmprospătați colectorul — **laptopul B trebuie să apară în listă**.

---

## Pasul 3 — Laptop C: tehnicianul se conectează

1. Copiați `remote-intune\rustdesk` pe C.
2. Editați `Configure-TechnicianClient.ps1`: puneți `$RD_HOST = "IP_A"` și `$RD_KEY = "CHEIA"`.
3. Rulați-l ca administrator.
4. Deschideți RustDesk pe C. Din colectorul de pe A luați **ID-ul și parola lui B** („Arată parola”).
5. Introduceți ID-ul lui B, apoi parola. **Vedeți și controlați ecranul lui B.**

---

## Ce să verificați (scenariile tale reale)

- **Fără accept pe B:** conexiunea pornește direct cu parola, nu trebuie nimeni la B. ✔ acces nesupravegheat.
- **Schimbarea userului:** pe B, faceți *Sign out* sau *Switch user*. De pe C, reconectați-vă — **trebuie să prindeți și ecranul de logon** (pentru că serviciul rulează ca SYSTEM).
- **UAC:** deschideți pe B ceva care cere drepturi de administrator (fereastra UAC). De pe C **trebuie să puteți da click în ea** (ecranul securizat).
- **Al doilea „angajat”:** repetați Pasul 2 și pe un alt laptop, ca să vedeți doi clienți în colector.
- **Auditul:** pe A, în colector, tab-ul „Jurnal audit” — fiecare „Arată parola” apare înregistrat.

## Dacă ceva nu merge
- B nu apare în colector → verificați `C:\ProgramData\CarpaticaRemote\install.log` pe B (token/URL greșit sau firewall închis pe A).
- C nu se conectează la B → verificați că ambele au aceeași `CHEIE` și `IP_A`, și că `hbbs.exe`/`hbbr.exe` rulează pe A. Ca alternativă fără server: pe B activați RustDesk → Settings → Security → **Enable direct IP access** și conectați de pe C direct pe `IP-ul lui B`.

## După test
Pe B (și pe orice laptop de test), ca administrator:
```
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```
