# PDF Studio – contract intern între module (Python 3.10+)

Aplicație locală: backend FastAPI (`app/main.py`) servește UI web din `app/static/` pe http://127.0.0.1:8765.
Toate funcțiile lucrează cu `bytes` in / `bytes` out. Erorile de utilizator se aruncă ca `ValueError("mesaj în română")`.
Textele vizibile utilizatorului: în limba română.

## app/signing.py  (pyHanko, asn1crypto, python-pkcs11)
- `DEFAULT_PKCS11_LIBS: dict[str, list[str]]` – chei "windows"/"linux"/"darwin", căi uzuale pt token-uri (SafeNet eToken, certSIGN, Trans Sped, DigiSign/Bit4id, Gemalto IDPrime, AlfaTrust etc.)
- `detect_pkcs11_libs() -> list[str]` – căile din listă care există pe sistem
- `list_pkcs11_tokens(lib_path: str) -> list[dict]` → `{slot_id, label, manufacturer, serial}`
- `list_token_certs(lib_path: str, token_label: str, pin: str) -> list[dict]` → `{label, key_id (hex), subject, issuer, not_after (iso), email}`
- `sign_pdf(pdf: bytes, *, method: str, params: dict, field_name: str|None=None, reason: str|None=None, location: str|None=None, contact: str|None=None, visible: dict|None=None, timestamp_url: str|None=None) -> bytes`
  - method "pkcs12": params `{pfx: bytes, password: str}`
  - method "pkcs11": params `{lib_path, token_label, pin, cert_label|None, key_id|None}`
  - method "csc" (semnătură în cloud, Cloud Signature Consortium API v1/v2 – certSIGN Paperless, Trans Sped, DigiSign cloud etc.): params `{service_url, access_token, credential_id, pin|None, otp|None}`
  - visible: `{page: int (0-based), x, y, w, h}` în puncte PDF (origine stânga-jos) sau None pt invizibilă
  - semnătura PAdES (B-B, sau B-T când timestamp_url e dat), incrementală (păstrează semnăturile existente)
- `validate_pdf(pdf: bytes, extra_trust_roots: list[bytes]|None=None) -> list[dict]` câte una pe semnătură:
  `{field, signer_name, signer_email, signing_time (iso|None), intact (bool), valid (bool), trusted (bool), coverage (str), modification_level (str), timestamp (iso|None), cert_subject, cert_issuer, cert_not_after, summary (str, română), errors (list[str])}`
- `make_test_pfx(common_name: str, email: str, password: str) -> bytes` – certificat auto-semnat pt teste/demo

## app/convert.py
- `pdf_to_docx(pdf: bytes) -> bytes` (pdf2docx)
- `office_to_pdf(data: bytes, filename: str) -> bytes` (docx/doc/odt/rtf/xlsx/pptx/txt; LibreOffice headless `soffice`; pe Windows fallback MS Word via docx2pdf/COM dacă e instalat)
- `find_soffice() -> str|None`

## app/editor.py (PyMuPDF / fitz)
- `info(pdf) -> dict` → `{pages, page_sizes: [[w,h],...], metadata: dict, encrypted: bool, signature_count: int}`
- `render_page(pdf, page: int, zoom: float=1.5) -> bytes` (PNG)
- `apply_edits(pdf, ops: list[dict]) -> bytes`; coordonatele în puncte PDF, origine STÂNGA-SUS (ca în PyMuPDF). Op-uri (`type`):
  `add_text{page,x,y,text,size=12,color="#000000"}`, `highlight{page,rect:[x0,y0,x1,y1]}`, `rect{page,rect,color,fill|None,width}`,
  `whiteout{page,rect}`, `redact{page,rect}` (eliminare reală a conținutului), `image{page,rect,image_b64}`,
  `replace_text{search,replace,page|None}`, `rotate{page,angle}`, `delete_page{page}`, `move_page{from,to}`,
  `insert_blank{at}`, `note{page,x,y,text}`, `set_metadata{title,author,subject,keywords}`
- `merge(pdfs: list[bytes]) -> bytes`
- `split(pdf, ranges: str) -> list[bytes]` – ex. "1-3,4,5-end" (1-based)
- `extract_text(pdf) -> str`
- `compress(pdf) -> bytes`

## app/workflow.py (SQLite + SMTP + IMAP, fără server extern)
Model: inițiatorul creează un flux cu semnatari (ordine secvențială). Fiecare semnatar primește PDF-ul pe e-mail
(subiect conține tag `[PDFS-<id>]`), îl semnează (cu această aplicație sau oricare altă) și răspunde cu PDF-ul semnat.
Răspunsul este importat (IMAP automat sau upload manual), validat (`signing.validate_pdf`), apoi se trimite la următorul.
La final toți primesc documentul complet semnat.
- `class WorkflowStore(db_path: str)`
  - `get_settings() -> dict` / `save_settings(d: dict)` – smtp_host, smtp_port, smtp_user, smtp_password, smtp_tls ("ssl"|"starttls"|"none"), from_email, from_name, imap_host, imap_port, imap_user, imap_password, imap_folder
  - `create(name, pdf: bytes, filename, signers: list[{email,name}], message: str="") -> int`
  - `list() -> list[dict]`, `get(id) -> dict` (include `signers` cu status `pending|sent|signed|rejected`, `events`, `current_step`, `status` `draft|in_progress|completed|cancelled`)
  - `get_document(id) -> (filename, bytes)` – versiunea curentă
  - `start(id)` – trimite către primul semnatar
  - `submit_signed(id, pdf: bytes, source="manual") -> dict` – validează, avansează, trimite următorul / finalizează; returnează raport
  - `sign_current_step_locally(id, signed_pdf: bytes)` = alias pt submit_signed cu source="local"
  - `remind(id)`, `cancel(id)`
  - `check_inbox() -> list[dict]` – citește IMAP, importă atașamentele PDF din mesajele cu tag
  - `test_smtp() / test_imap()`
