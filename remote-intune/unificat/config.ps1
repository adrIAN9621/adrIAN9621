# ============================================================================
#  Carpatica Asistență IT – INSTALATOR UNIC (RustDesk + agent „cu acord")
#  CONFIGURAȚIE UNICĂ. Editați DOAR acest fișier înainte de a împacheta pachetul.
#  Toate scripturile din acest folder citesc valorile de aici.
# ============================================================================

# ----------------------------------------------------------------------------
#  1) SERVERUL UNIFICAT (consola + WebSocket agent + API de înregistrare)
# ----------------------------------------------------------------------------

# URL-ul de bază al serverului unificat (schema + gazdă + port). FĂRĂ „/" la final.
# Exemplu tipic: https://server.carpatica:8443
$SERVER_URL   = "https://server.carpatica:8443"

# Tokenul de înregistrare (ingest_token). Se obține pe server cu:
#     python -m server token
# Cu el, laptopul raportează ID-ul + parola RustDesk la /api/register.
$INGEST_TOKEN = "SCHIMBATI_ACEST_TOKEN"

# --- URL-uri derivate automat din $SERVER_URL (de regulă NU le modificați) ---
# Endpoint-ul de înregistrare a laptopului (POST JSON + Bearer ingest_token).
$REGISTER_URL = ($SERVER_URL.TrimEnd('/')) + "/api/register"
# WebSocket-ul agentului „cu acord" (ws:// / wss://, derivat din schema serverului).
$AGENT_WS_URL = (($SERVER_URL -replace '^https://','wss://') -replace '^http://','ws://').TrimEnd('/') + "/ws/agent"

# ----------------------------------------------------------------------------
#  2) RUSTDESK – serverul vostru (hbbs/hbbr) din rețeaua companiei
# ----------------------------------------------------------------------------

# Gazda (IP sau nume DNS) pe care rulează hbbs ȘI hbbr.
$RD_HOST  = "rustdesk.carpatica.local"

# Cheia publică a serverului: conținutul fișierului id_ed25519.pub din folderul
# de date al serverului (o singură linie, fără ghilimele). Obligatorie pentru
# conexiuni criptate la serverul propriu.
$RD_KEY   = "PUNETI_AICI_CHEIA_PUBLICA_id_ed25519.pub"

# Serverul releu (hbbr). De regulă aceeași gazdă. Lăsați gol pentru deducere automată.
$RD_RELAY = $RD_HOST

# API server (doar la RustDesk Server Pro). Gol la varianta open-source.
$RD_API   = ""

# --- Parola de acces nesupravegheat ---
# "random"   = fiecare laptop primește o parolă proprie, raportată la server. RECOMANDAT.
# "<parola>" = o parolă fixă, comună pe toată flota (mai simplu, mai riscant).
$RD_PASSWORD   = "random"
$RD_RANDOM_LEN = 16

# approve-mode: "password" = IT se conectează doar cu parola (nesupravegheat).
#               "password-click" = parolă SAU accept de la utilizator.
$RD_APPROVE_MODE = "password"

# Instalează și pornește serviciul Windows (necesar pentru acces la logon / UAC
# și pentru a funcționa când se schimbă userii). Lăsați $true.
$RD_INSTALL_SERVICE = $true

# Dacă rustdesk.exe este lângă scripturi (sau lângă rustdesk\install.ps1), se
# folosește acela. Altfel se descarcă ultima versiune de pe GitHub la instalare.
$RD_FALLBACK_DOWNLOAD = $true

# Numele produsului RustDesk în Programe instalate / jurnale.
$RD_PRODUCT = "Carpatica Remote (RustDesk)"

# ----------------------------------------------------------------------------
#  3) AGENTUL „cu acord" (Carpatica-Asistenta-IT.exe)
# ----------------------------------------------------------------------------

# Numele executabilului construit cu it-asistenta\agent\build_exe.bat.
# Scriptul îl caută lângă el (în acest folder). Construiți-l ÎNTÂI (vezi README).
$AGENT_EXE_NAME = "Carpatica-Asistenta-IT.exe"

# Numele produsului agent în Program Files / scurtături.
$AGENT_PRODUCT  = "Carpatica Asistenta IT"

# Verificare TLS la conexiunea agentului către server. Lăsați $true în producție.
# Puneți $false DOAR pentru teste cu certificat autosemnat fără CA distribuit.
$AGENT_VERIFY_TLS = $true

# (Opțional) Cale către un fișier CA (.pem) pe care agentul să-l folosească la
# verificarea certificatului serverului. Gol = magazinul implicit de certificate.
# Dacă dați un nume simplu, se caută lângă executabilul agentului din Program Files.
$AGENT_CA_FILE = ""
