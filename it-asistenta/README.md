# Carpatica Asistență IT – control de la distanță pentru intervenții IT

Aplicație internă pentru **Carpatica Feroviar România SA**, cu care departamentul IT vede și controlează de la distanță calculatorul unui angajat (în stilul AnyDesk sau TeamViewer). Codul e scris integral de noi, nu are licențe plătite și nu folosește servere externe. Tot traficul trece doar prin serverul companiei.

```
 PC angajat                    Server companie                   Tehnician IT
┌───────────────┐   wss    ┌──────────────────────┐   https   ┌──────────────┐
│ Agent (.exe)  │ ───────► │ Server releu + audit │ ◄──────── │ Consolă web  │
│ ID + cod      │  ecran ► │ (FastAPI, SQLite)    │ ◄ mouse/  │ (browser)    │
│ consimțământ  │ ◄ input  │ port 8443 (TLS)      │   tastatură│              │
└───────────────┘          └──────────────────────┘           └──────────────┘
```

## Cum funcționează o intervenție
1. Angajatul pornește **Carpatica Asistență IT** și îi dictează tehnicianului **ID-ul** (9 cifre) și **codul** (6 cifre).
2. Tehnicianul se autentifică în consola web (`https://server:8443`), apoi introduce ID-ul și codul.
3. Pe ecranul angajatului apare cererea: *„Tehnicianul X solicită acces…”*, cu butoanele **Permite** și **Refuză**.
4. Cât timp durează sesiunea, angajatul vede o bară „Sesiune de asistență activă”. Din ea poate bifa „Doar vizualizare”, poate scrie în chat sau poate închide sesiunea oricând.
5. Fiecare acțiune intră în jurnalul de audit: cine s-a conectat, la ce calculator, când și cât a durat.

## Instalare server (o singură dată, de către IT)
Pe un server Windows sau Linux din rețeaua companiei, cu Python 3.10 sau mai nou:
```bash
cd it-asistenta
pip install -r server/requirements.txt
python -m server gencert            # certificat TLS (sau puneți certificatul companiei în config.json)
python -m server adduser ion.popescu   # creați câte un cont pentru fiecare tehnician
python -m server                    # pornește serverul pe portul 8443
```
- Deschideți în firewall portul **8443/TCP**, doar pentru rețeaua internă sau VPN.
- Dacă folosiți certificatul generat cu `gencert` (auto-semnat), copiați fișierul `.crt` lângă agent și treceți-l la `ca_file` în configurația agentului.

## Instalare agent pe calculatoare
1. Editați `agent/config.json` (pornind de la `config.example.json`) și puneți adresa serverului, de exemplu `wss://it.carpatica.local:8443/ws/agent`.
2. Construiți executabilul pe un PC cu Windows și Python: `agent\build_exe.bat`. Rezultă `Carpatica-Asistenta-IT.exe`.
3. Distribuiți executabilul împreună cu `config.json` (și cu `.crt`, dacă e cazul) prin GPO, Intune sau un share de rețea. Puneți și o scurtătură pe desktop.

## Securitate
- Toate conexiunile sunt criptate cu TLS.
- Tehnicienii au conturi nominale, cu parolă salvată ca hash PBKDF2. După mai multe încercări greșite, contul se blochează temporar.
- Fiecare sesiune are nevoie de codul afișat pe ecranul angajatului și de **acceptul explicit** al acestuia. Fără accept nu se poate prelua controlul.
- ID-ul unui calculator e legat de o cheie secretă locală, deci nu poate fi preluat de alt calculator.
- Jurnalul de audit e complet și se vede în consolă, la tab-ul *Jurnal*.

## Limitări în versiunea 1
- Ecranul Ctrl+Alt+Del și ferestrele UAC (cele care cer drepturi de administrator) nu se pot controla, pentru că agentul rulează ca aplicație de utilizator. Pentru asta e nevoie de un serviciu Windows, planificat pentru versiunea 2.
- Fără acces nesupravegheat: la fiecare sesiune trebuie să existe cineva lângă calculator care să accepte.
- Transferul de fișiere nu e inclus încă. Textul se poate trimite prin chat sau prin clipboard.
