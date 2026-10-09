# Testare locală (fără server al companiei)

Cum probați fiecare componentă pe propriul laptop, înainte de orice rulout.

---

## 1. PDF Studio — complet local
Nu are nevoie de niciun server.
```
cd pdf-studio
start_windows.bat         (Windows)   sau   ./start.sh   (Linux/macOS)
```
Se deschide în browser la `http://127.0.0.1:8765`. Semnarea, validarea, conversia și editarea merg offline. Fluxurile de e-mail au nevoie de un cont SMTP/IMAP real doar dacă vreți să testați trimiterea; restul merge fără.

---

## 2. Carpatica Asistență IT — cap-coadă pe un singur laptop
Serverul și agentul rulează pe aceeași mașină, pe `127.0.0.1`. Fără server extern.

**Terminal 1 – serverul:**
```
cd it-asistenta
pip install -r server/requirements.txt
python -m server adduser test          (puneți o parolă când o cere)
# pornire fără TLS, doar pentru test local:
#   editați server/config.json -> "allow_insecure": true
python -m server
```
Deschideți consola la `http://127.0.0.1:8443` (user „test”).

**Terminal 2 – agentul (angajatul):**
Creați `agent/config.json`:
```json
{ "server_url": "ws://127.0.0.1:8443/ws/agent", "verify_tls": false, "allow_insecure": true }
```
```
pip install -r agent/requirements.txt
python agent/carpatica_agent.py
```
Agentul afișează un ID și un cod. În consolă introduceți ID-ul + codul, acceptați cererea în fereastra agentului — și vedeți propriul ecran controlat de la distanță. Totul pe un singur calculator.

> Dacă vreți două calculatoare: pe al doilea puneți în `server_url` IP-ul din LAN al primului (ex. `ws://192.168.1.50:8443/ws/agent`) și deschideți portul 8443 în firewall.

---

## 3. RustDesk (remote-intune) — opțiuni de test fără serverul companiei

RustDesk are nevoie fie de un server de întâlnire, fie de conexiune directă pe IP. Trei variante, de la cea mai ușoară:

### A. Validarea instalării pe un singur laptop (fără control)
Verifică doar că scriptul merge: instalează serviciul, scoate ID-ul, setează parola, scrie `device-info.txt`.
1. În `remote-intune/rustdesk/config.ps1` lăsați `$RD_HOST = "127.0.0.1"` și `$RD_KEY` gol.
2. Click dreapta pe `Instaleaza-Manual.bat` → **Run as administrator**.
3. La final vedeți ID-ul și parola. Verificați în *Services* că serviciul „RustDesk” rulează.
Nu vă puteți controla pe voi înșivă, dar confirmați că instalarea și raportarea funcționează.

### B. Control real, fără NICIUN server — conexiune directă pe IP (recomandat)
Trebuie **două mașini în aceeași rețea** (un al doilea laptop sau un VM gratuit — Hyper-V, VirtualBox).
1. Instalați RustDesk pe ambele (pe ținta, cu `Instaleaza-Manual.bat`; pe tehnician, clientul normal).
2. Pe mașina-țintă: RustDesk → **Settings → Security → Enable direct IP access**.
3. Pe tehnician: în bara de conectare introduceți `IP-ul-țintei` (ex. `192.168.1.77`) în loc de ID și parola de acces nesupravegheat.
Astfel testați controlul complet (inclusiv UAC și schimbarea userilor) fără server de întâlnire.

### C. Server RustDesk local pe laptopul vostru
Dacă vreți exact fluxul bazat pe server, dar local:
1. Rulați serverul pe laptop (Docker Desktop):
   ```
   docker run --name hbbs -v %cd%/data:/root -td -p 21115:21115 -p 21116:21116 -p 21116:21116/udp -p 21118:21118 rustdesk/rustdesk-server hbbs
   docker run --name hbbr -v %cd%/data:/root -td -p 21117:21117 -p 21119:21119 rustdesk/rustdesk-server hbbr
   ```
   (pe Windows, fără `--net=host`; folosiți `-p` ca mai sus).
2. Luați cheia din `data/id_ed25519.pub` și puneți-o în `config.ps1` la `$RD_KEY`, cu `$RD_HOST = "127.0.0.1"` (sau IP-ul din LAN pentru a doua mașină).
3. Rulați `Instaleaza-Manual.bat`. Pentru control real conectați de pe a doua mașină din LAN.

---

## 4. Colectorul intern — local
```
cd remote-intune/collector
pip install -r requirements.txt
python -m collector init           # generează config.json cu token + secret
# pentru test local fără certificat: editați config.json -> "allow_insecure": true
python -m collector adduser test
python -m collector
```
Deschideți `http://127.0.0.1:8070`. Puteți simula un laptop care raportează:
```
curl -k -X POST http://127.0.0.1:8070/api/register ^
  -H "Authorization: Bearer <ingest_token din config.json>" ^
  -H "Content-Type: application/json" ^
  -d "{\"id\":\"123456789\",\"password\":\"Test123\",\"hostname\":\"LAPTOP-TEST\",\"user\":\"ion\"}"
```
Reîmprospătați pagina — apare laptopul; „Arată parola” scrie și în jurnalul de audit.

---

## Rezumat
| Componentă | Test pe un singur laptop | Server companiei necesar |
|---|---|---|
| PDF Studio | Da, complet | Nu |
| Asistență IT | Da, cap-coadă | Nu |
| RustDesk – instalare | Da (varianta A) | Nu |
| RustDesk – control real | Nevoie de 2 mașini (varianta B, IP direct) | Nu |
| Colector | Da, complet | Nu |
