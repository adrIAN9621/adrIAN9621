# ============================================================================
#  Carpatica Feroviar – configurație instalare RustDesk (acces nesupravegheat)
#  Editați DOAR acest fișier înainte de a împacheta pachetul.
# ============================================================================

# --- Serverul vostru RustDesk (hbbs/hbbr) din rețeaua companiei ---
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
# "random"  = fiecare laptop primește o parolă proprie, salvată local și
#             raportată (vezi $RD_REPORT_URL). RECOMANDAT.
# "<parola>" = o parolă fixă, comună pe toată flota (mai simplu, mai riscant).
$RD_PASSWORD = "random"
$RD_RANDOM_LEN = 16

# Unde se raportează ID-ul + parola fiecărui laptop (opțional).
# Dacă e gol, informațiile rămân doar local în device-info.txt.
# Poate fi un endpoint intern care acceptă POST JSON {id,password,hostname,user}.
$RD_REPORT_URL = ""

# --- Comportament ---
# approve-mode: "password" = IT se conectează doar cu parola, fără ca cineva să
#   apese „Accept” (acces nesupravegheat). "password-click" = parolă SAU accept.
$RD_APPROVE_MODE = "password"

# Instalează și pornește serviciul Windows (necesar pentru acces la logon / UAC
# și pentru a funcționa când se schimbă userii). Lăsați $true.
$RD_INSTALL_SERVICE = $true

# Dacă rustdesk.exe este lângă scripturi, se folosește acela (recomandat pentru
# Intune). Altfel se descarcă ultima versiune de pe GitHub la instalare.
$RD_FALLBACK_DOWNLOAD = $true

# Numele produsului în Programe instalate / jurnale.
$RD_PRODUCT = "Carpatica Remote (RustDesk)"
