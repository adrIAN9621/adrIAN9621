# Colector RustDesk – Carpatica Feroviar

Serviciu web intern pentru echipa IT. Primește înregistrările dispozitivelor
RustDesk (ID + parolă de acces neasistat + hostname) de la laptopurile Windows
gestionate prin Intune și permite tehnicienilor să le caute și să recupereze
parola la nevoie.

Parolele **nu** ajung în portalul Intune: ele merg doar către acest colector
intern, sunt **criptate în repaus** și sunt dezvăluite doar printr-un apel
autentificat, consemnat în jurnalul de audit.

---

## Cerințe

- Python 3.10 sau mai nou
- Pachetele din `requirements.txt`:

```bash
pip install -r requirements.txt
```

(pentru teste: `pip install pytest httpx`)

---

## Configurare (`config.json`)

Fișierul `config.json` se află lângă pachet. Câmpuri:

| Câmp              | Descriere                                                        |
|-------------------|------------------------------------------------------------------|
| `host`            | Adresa de ascultare (implicit `0.0.0.0`).                        |
| `port`            | Portul (implicit `8070`).                                        |
| `certfile`        | Calea către certificatul TLS (PEM).                              |
| `keyfile`         | Calea către cheia privată TLS (PEM).                             |
| `allow_insecure`  | `true` pornește **fără TLS** – DOAR pentru testare locală.       |
| `db`              | Calea bazei de date SQLite (implicit `collector.db`).            |
| `ingest_token`    | Token Bearer pe care îl folosesc laptopurile la `/api/register`. |
| `enc_secret`      | Secret din care se derivă cheia de criptare a parolelor.         |
| `session_ttl`     | Durata de viață a sesiunii web, în secunde.                      |

> Pornirea serverului este **refuzată fără TLS**, cu un mesaj explicit, dacă
> `allow_insecure` nu este `true`.

Puteți genera un `config.json` implicit (cu `ingest_token` și `enc_secret`
aleatorii) cu:

```bash
python -m collector init
```

**Unde se află secretele:**
- `ingest_token` și `enc_secret` se află **doar** în `config.json`
  (recomandat: `chmod 600 config.json`). Nu sunt scrise niciodată în baza de
  date și nu părăsesc serverul.

---

## Pornire

Toate comenzile se rulează din directorul `remote-intune/` (părintele
pachetului `collector`).

```bash
# 1. Generați un token de ingestie și puneți-l în config.json + în scriptul PS1
python -m collector gentoken

# 2. Generați un certificat TLS autosemnat (intern)
python -m collector gencert --hostname rustdesk.carpatica.local

# 3. Creați cel puțin un cont de tehnician (parola se cere interactiv)
python -m collector adduser ion.popescu

# 4. Porniți serverul
python -m collector
```

Alte comenzi:

```bash
python -m collector deluser ion.popescu   # șterge un tehnician
python -m collector --config /cale/config.json run
```

Interfața web: `https://<host>:8070/` – autentificare cu contul de tehnician.

---

## Endpoint-uri

### `POST /api/register` (apelat de laptopuri)
- Autentificare: antet `Authorization: Bearer <ingest_token>` (comparație în
  timp constant).
- Corp JSON: `{id, password, hostname, server, user, reported}`.
- Validează ID-ul RustDesk (9–10 cifre), respinge corpurile supradimensionate,
  limitează rata per IP.
- *Upsert* după ID: actualizează hostname/parolă/utilizator/ultima raportare,
  păstrează `first_seen`. Parola este criptată înainte de stocare.
- Răspuns: `{ "ok": true }`.

### Interfață tehnician (sesiune separată de token-ul de ingestie)
- `GET /` – pagina de autentificare sau tabloul de bord.
- `POST /login` / `POST /logout` – cookie de sesiune `HttpOnly`, `SameSite=Strict`,
  `Secure` sub TLS. Parole PBKDF2-SHA256 (200.000 iterații, sare per utilizator).
  Blocare după 5 autentificări eșuate de la aceeași IP.
- `GET /api/devices` – lista dispozitivelor (hostname, ID formatat „123 456 789”,
  utilizator, ultima raportare, vechime). **Parolele NU sunt incluse.**
- `GET /api/devices/{id}/password` – dezvăluie parola (decriptată), necesită
  sesiune și **scrie o linie în jurnalul de audit** (cine, ce dispozitiv, când,
  de la ce IP).
- `GET /api/audit` – jurnalul dezvăluirilor de parolă.

---

## Legătura cu `remediation/Remediate-ReportDeviceInfo.ps1`

Scriptul de remediere Intune
`../rustdesk/remediation/Remediate-ReportDeviceInfo.ps1` trimite datele
laptopului către acest colector. Pentru a funcționa, cele două trebuie să
corespundă:

| În scriptul PowerShell | În colector (`config.json`) |
|------------------------|-----------------------------|
| `$REPORT_URL = "https://rustdesk.carpatica.local:8070/api/register"` | `host` + `port` + certificat TLS pentru acel hostname |
| `$REPORT_TOKEN = "..."`  | `ingest_token` (**exact aceeași valoare**) |

Scriptul trimite JSON-ul `{id, password, hostname, server, user, reported}` cu
antetul `Authorization: Bearer $REPORT_TOKEN`. După generarea unui token nou
(`python -m collector gentoken`), actualizați `$REPORT_TOKEN` în script și
`ingest_token` în `config.json`.

---

## Note de securitate

- **TLS obligatoriu**: serverul refuză pornirea fără certificat/cheie, cu
  excepția modului explicit de testare (`allow_insecure: true`). Folosiți TLS
  intern (CA intern sau certificat autosemnat distribuit pe laptopuri).
- **Parole criptate în repaus**: parolele RustDesk sunt criptate cu Fernet
  (AES-128-CBC + HMAC), cheia fiind derivată din `enc_secret` prin PBKDF2.
  Decriptarea are loc **doar** la apelul autentificat către endpoint-ul de
  parolă; lista în masă nu conține niciodată parole în clar.
- **Audit al dezvăluirilor**: fiecare afișare de parolă este consemnată
  (utilizator, dispozitiv, oră, IP) și vizibilă în fila „Jurnal audit”.
- **Separarea credențialelor**: token-ul de ingestie (pentru laptopuri) este
  complet separat de conturile de tehnician (pentru interfața web).
- **Întărire**: comparație în timp constant pentru token și parole, limitare de
  rată la ingestie, blocare la autentificare, antete de securitate și
  `Content-Security-Policy: default-src 'self'`, cookie `HttpOnly`/`SameSite=Strict`.
- Protejați `config.json` și fișierul bazei de date (`chmod 600`), întrucât conțin
  secretele, respectiv parolele criptate.
