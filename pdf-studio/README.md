# PDF Studio – Carpatica Feroviar România SA

Instrument intern pentru documente PDF.

O aplicație pentru uz personal sau intern, care rulează doar pe calculatorul tău (`http://127.0.0.1:8765`). Acoperă funcțiile Adobe Acrobat folosite cel mai des:

| Funcție | Ce face |
|---|---|
| **Semnare digitală** | Semnătură PAdES cu **token USB** (PKCS#11: SafeNet/eToken, certSIGN, DigiSign/Bit4id, Trans Sped, IDPrime, OpenSC…), cu **fișier .pfx/.p12** sau cu **cont cloud** (API CSC: certSIGN Paperless, Trans Sped, DigiSign etc.). Semnătura poate fi vizibilă (o poziționezi cu mouse-ul) sau invizibilă și poate avea marcă temporală (TSA). Semnăturile existente rămân valide, pentru că fiecare semnătură nouă se adaugă incremental. |
| **Validare semnături** | Verifică integritatea (dacă documentul a fost modificat după semnare), validitatea criptografică, încrederea în emitent (se pot adăuga certificate rădăcină), cine a semnat, când și cu ce marcă temporală. |
| **Conversie** | PDF → Word (.docx) și Word/Office (docx, doc, odt, rtf, xlsx, pptx) → PDF |
| **Editare PDF** | Text (cu diacritice), evidențiere, dreptunghiuri, acoperire albă, ștergere definitivă (redactare), imagini, note, înlocuire text, rotire/ștergere/mutare/inserare pagini, metadate, combinare, împărțire, comprimare, extragere text |
| **Fluxuri de semnare pe e-mail** | Stabilești ordinea semnatarilor după adresa de e-mail. Fiecare primește documentul pe rând, îl semnează și răspunde cu PDF-ul semnat. Aplicația preia răspunsul (automat prin IMAP sau prin încărcare manuală), verifică semnăturile, apoi trimite documentul următorului semnatar. La final, toți primesc documentul complet. |

## Descărcare ca aplicație Windows (.exe, fără Python)
Dacă nu vrei să instalezi Python, poți folosi un singur fișier `PDF-Studio.exe`:

**Varianta 1 – construit automat pe GitHub (recomandat):**
1. Pe GitHub, în repo, deschide tab-ul **Actions → „Construire aplicații Windows” → Run workflow** (alege ramura `claude/pdf-studio`).
2. Aștepți ~5 minute să se termine (bifă verde).
3. Intri în rularea respectivă și descarci, din secțiunea **Artifacts**, arhiva **PDF-Studio-Windows**. Înăuntru e `PDF-Studio.exe`.
4. Dublu-clic pe `.exe` → se deschide în browser. Fără instalare.

**Varianta 2 – construit local:** pe un PC cu Windows + Python, rulează `pdf-studio\build_exe.bat`. Rezultatul e `pdf-studio\dist\PDF-Studio.exe`.

> Pentru conversia Word ↔ PDF e nevoie, și cu `.exe`, de **LibreOffice** instalat pe PC. Restul funcțiilor (semnare, validare, editare) merg fără nimic în plus.

## Instalare

### Windows
1. Instalează **Python 3.10+** de pe [python.org](https://www.python.org/downloads/) și bifează „Add Python to PATH”.
2. Pentru conversia Word → PDF instalează **LibreOffice** (gratuit). Dacă ai Microsoft Word, se folosește automat pentru .docx.
3. Pentru token USB instalează driverul/middleware-ul primit de la furnizorul certificatului (SafeNet Authentication Client, Bit4id etc.).
4. Dă dublu-click pe **`start_windows.bat`**. La prima pornire se instalează dependențele, apoi se deschide browserul.

### Linux / macOS
```bash
./start.sh
```
Ai nevoie de `python3`, `libreoffice` și, pentru token, de biblioteca PKCS#11 a furnizorului.

## Semnare cu token USB
1. Mergi la **Semnare → Token USB**. Aplicația caută singură bibliotecile PKCS#11 cunoscute. Dacă nu o găsește pe a ta, introdu calea manual, de exemplu:
   - SafeNet: `C:\Windows\System32\eTPKCS11.dll`
   - Bit4id (DigiSign / certSIGN): `C:\Windows\System32\bit4xpki.dll`
   - Thales/Gemalto IDPrime: `C:\Windows\System32\IDPrimePKCS11.dll`
2. Apasă „Caută token-uri”, introdu PIN-ul, apasă „Încarcă certificate”, alege certificatul și semnează.

## Semnare cu cont cloud (CSC)
Furnizorii care oferă semnătură calificată în cloud îți pun la dispoziție adresa serviciului CSC (`.../csc/v1`), un token de acces OAuth2 și ID-ul credențialului. Le introduci în tab-ul **Cont cloud**. PIN-ul și OTP-ul se cer doar dacă furnizorul le solicită.

## Fluxuri de semnare
1. În **Setări** completezi contul de e-mail: SMTP pentru trimitere și IMAP pentru preluarea automată a răspunsurilor. Pentru Gmail sau Outlook folosește o *parolă de aplicație*.
2. În **Fluxuri de semnare** creezi un flux: încarci PDF-ul și adaugi semnatarii în ordine.
3. Fiecare semnatar primește un e-mail cu subiectul `[PDFS-<nr>] ...` și PDF-ul atașat. Îl semnează cu orice aplicație (PDF Studio, Adobe Reader etc.) și răspunde cu PDF-ul semnat atașat.
4. Apasă „Verifică inbox” sau încarcă manual PDF-ul primit. Aplicația verifică dacă semnăturile anterioare sunt intacte și dacă a apărut semnătura nouă, apoi trimite mai departe.
5. Dacă ești tu semnatarul curent, folosește „Semnez eu acum”.

Datele (fluxuri, setări, versiunile documentelor) se salvează în `~/.pdf-studio/workflows.db`. Poți schimba locația cu variabila de mediu `PDFSTUDIO_DATA`.

## Teste
```bash
pip install pytest
pytest -q
```

## Limitări
- Editarea unui PDF deja semnat invalidează semnăturile. Aplicația te avertizează când se întâmplă asta.
- Conversia PDF → Word reproduce bine documentele de tip text. Documentele scanate (imagini) nu devin text editabil fără OCR.
- Lista certificatelor de încredere folosește rădăcinile sistemului. Pentru CA-urile calificate din România care lipsesc, încarcă certificatul rădăcină la validare.

## Identitate vizuală
Tema folosește culorile albastru feroviar și galben de semnalizare, iar în bara laterală apare un tren de marfă.
Sigla din aplicație este provizorie. Pentru sigla oficială, înlocuiți fișierul `app/static/brand/logo.svg`
cu sigla companiei, păstrând același nume. Culorile se schimbă din `app/static/app.css`, secțiunea `:root`
(`--primary` și `--accent`).

## Instalator Windows (setup cu scurtătură pe desktop)
Pentru un instalator normal (`PDF-Studio-Setup.exe`) care instalează aplicația și pune scurtătură pe desktop:
1. Pe un PC cu Windows + Python, instalează o dată **Inno Setup** (gratuit): https://jrsoftware.org/isdl.php
2. Dublu-clic pe `pdf-studio\build_installer.bat`.
3. Rezultatul: `pdf-studio\installer\Output\PDF-Studio-Setup.exe`.

Acel fișier e instalatorul: îl copiezi pe orice laptop, dublu-clic, Next-Next, și apare scurtătura pe desktop ca la orice program.

## Aplicație de sine stătătoare (fereastră proprie, nu browser)
Începând cu această versiune, `PDF-Studio.exe` se deschide în **fereastra lui**, ca orice program (se deschide în fereastra ei proprie, fără bară de adrese (modul „aplicație” al Microsoft Edge/Chrome, prezent pe orice Windows 10/11). Nu mai apare ca pagină de browser. Dacă din întâmplare nu găsește Edge/Chrome, revine la browserul implicit. Un jurnal de pornire se scrie în %LOCALAPPDATA%\PDF-Studio\startup.log.
