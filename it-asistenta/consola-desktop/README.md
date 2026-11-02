# Consola tehnicienilor — aplicație desktop

Launcher care deschide **consola** (`https://asistenta.carpaticaferoviar.ro`) într-o
**fereastră proprie**, ca o aplicație desktop normală (fără bara de adrese a
browserului). Rulează ca **utilizator obișnuit** — autentificarea se face din
consolă, cu butonul **Autentificare** din dreapta-sus. Fiecare tehnician se
loghează cu contul lui.

## Construire (o dată, pe un Windows cu Python 3.10+)
```
cd it-asistenta\consola-desktop
build_exe.bat
```
Rezultă `dist\Carpatica-Consola-IT.exe` + `dist\config.json` alături.

## Configurare
`config.json` (lângă `.exe`) ține adresa serverului:
```json
{ "console_url": "https://asistenta.carpaticaferoviar.ro" }
```
O poți schimba fără reconstruire (ex. pentru alt server/test).

## Distribuire
- **Manual:** copiezi `Carpatica-Consola-IT.exe` + `config.json` (împreună) pe
  calculatorul tehnicianului; dublu-click → se deschide consola.
- **Intune:** împachetează ca aplicație Win32 (ca la agent). Pune o scurtătură pe
  Desktop/Start spre `.exe`.

## Cerințe
- Un browser Chromium instalat (Edge/Chrome/Brave) — launcher-ul deschide fereastra
  prin el (fără bara de adrese). Dacă nu găsește niciunul, deschide consola în
  browserul implicit.
- Calculatorul tehnicianului pe **rețea/VPN** (ca să ajungă la server) + CA-ul
  intern de încredere (ca la celelalte site-uri interne).

## Conectarea la dispozitive (RustDesk)
În tab-ul **Dispozitive**, butonul **Conectează (RustDesk)** dezvăluie parola
(acțiune auditată), o copiază în clipboard și deschide clientul RustDesk direct pe
ID-ul dispozitivului. Lipești parola (Ctrl+V) când RustDesk o cere.
> Necesită clientul RustDesk instalat și configurat pe serverul vostru (vezi
> `remote-intune/rustdesk/Configure-TechnicianClient.ps1`).
