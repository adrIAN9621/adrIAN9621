# Carpatica Asistență IT – protocol intern (v1)

Componente (toate Python 3.10+, cod propriu, fără licențe plătite):
- `server/` – server releu + consolă web tehnicieni (FastAPI + WebSocket, SQLite). Rulează pe un server al companiei, un singur port HTTPS (implicit 8443). Pornire: `python -m server` din folderul `it-asistenta` (sau `server/run.py`).
- `agent/` – aplicație Windows pentru angajat (tkinter + mss + Pillow + pynput + websockets/`websocket-client`). Se împachetează cu PyInstaller într-un singur .exe.
Texte vizibile: în limba română. Identitate vizuală: Carpatica Feroviar (albastru #0b4f8a, galben semnal #f2a900, sidebar #0d2238).

## Principii de securitate
1. Conexiuni doar prin TLS (wss/https). Pentru teste se permite http/ws dacă `allow_insecure=true` în config.
2. Tehnicienii se autentifică (utilizator + parolă, hash PBKDF2-SHA256 în `server/config.json` sau în DB; comandă CLI `python -m server adduser <nume>`).
3. Angajatul vede pe ecran **ID** (9 cifre, permanent) și **cod de acces** (6 cifre, se regenerează după fiecare sesiune și la cerere). Tehnicianul trebuie să introducă ambele.
4. Angajatul trebuie să **accepte explicit** fiecare sesiune (dialog cu numele tehnicianului; refuz automat după 60s).
5. Pe durata sesiunii agentul arată o bară vizibilă „Sesiune de asistență activă – <tehnician>” cu buton **Încheie sesiunea** și opțiune „Doar vizualizare” (blochează controlul).
6. Jurnal de audit pe server (cine, ce PC, start/sfârșit, motiv încheiere, IP).
7. Legare ID ↔ `agent_secret` (32 bytes random generat la prima rulare, păstrat local): primul hello înregistrează secretul; ulterior un ID cu alt secret e respins (previne furtul ID-ului).

## Transport
WebSocket. Mesaje text = JSON cu câmpul `t`. Mesaje binare = cadre de imagine.

### Agent ↔ server: `wss://HOST:PORT/ws/agent`
- A→S `{"t":"hello","agent_id":"123456789","agent_secret":"<hex>","hostname","user","os","version","code":"482913"}`
- S→A `{"t":"welcome"}` sau `{"t":"error","message"}` (apoi închide)
- A→S `{"t":"code","code":"..."}` când codul se regenerează
- S→A `{"t":"request","session_id","tech":"Nume Tehnician"}` → agentul arată dialog de consimțământ
- A→S `{"t":"accept","session_id","monitors":[{"index":0,"width":1920,"height":1080,"primary":true},...]}` / `{"t":"reject","session_id"}`
- A→S `{"t":"ping"}` la 20s; S răspunde `{"t":"pong"}`

### Tehnician ↔ server
- HTTP: `POST /api/login {username,password}` → cookie de sesiune (HttpOnly, SameSite=Strict); `POST /api/logout`; `GET /api/me`;
  `GET /api/agents` (listă: agent_id, hostname, user, os, online, last_seen); `GET /api/audit?limit=200`.
- WS: `wss://HOST:PORT/ws/tech` (autentificat prin cookie)
  - T→S `{"t":"connect","agent_id","code"}`
  - S→T `{"t":"waiting"}` (se așteaptă acceptul) / `{"t":"error","message"}`
  - S→T `{"t":"started","session_id","hostname","monitors":[...]}`
  - S→T `{"t":"ended","reason"}`

### În sesiune (serverul doar retransmite între agent și tehnician)
Binar A→T (cadru de imagine, little-endian):
`[u8 tip=1][u32 seq][u16 x][u16 y][u16 w][u16 h][u16 screen_w][u16 screen_h]` + bytes JPEG (sau PNG dacă tip=2) – o „dală” (tile) care trebuie desenată la (x,y) pe un canvas de screen_w×screen_h (coordonate în rezoluția trimisă, poate fi scalată față de ecranul real).
Text A→T `{"t":"frame_done","seq"}` după ultima dală a unui cadru. T→A `{"t":"ack","seq"}` după ce a desenat. Agentul nu trimite cadrul seq+2 până nu primește ack pentru seq (control al fluxului, max 2 cadre în zbor). Agentul trimite doar dalele modificate (grilă 64×64 comparată cu cadrul anterior); primul cadru și la cerere (`{"t":"refresh"}`) – complet.
Text A→T `{"t":"cursor","x","y"}` opțional.

T→A (input), coordonate în spațiul `screen_w×screen_h` al ultimei dale; agentul le scalează la monitorul real:
- `{"t":"mouse","action":"move|down|up|wheel","x","y","button":"left|right|middle","dx","dy"}`
- `{"t":"key","action":"down|up","code":"KeyA","key":"a"}` (`KeyboardEvent.code`/`.key`)
- `{"t":"text","text":"..."}` (lipire text)
- `{"t":"refresh"}`, `{"t":"monitor","index":1}`, `{"t":"quality","quality":60,"scale":1.0,"fps":10}`
- `{"t":"clipboard","text"}` (ambele sensuri)
- `{"t":"chat","text","from"}` (ambele sensuri; agentul arată fereastră de chat)
- `{"t":"end"}` (ambele sensuri) → serverul trimite `ended` ambelor părți și scrie în audit
- `{"t":"view_only","value":true}` A→T: angajatul a blocat controlul; agentul ignoră input-ul cât e activ.

Limitări v1: Ctrl+Alt+Del / ecranul UAC securizat nu pot fi controlate dintr-un proces de utilizator obișnuit (necesită serviciu Windows – v2).
