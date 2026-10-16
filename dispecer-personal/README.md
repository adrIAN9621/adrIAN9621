# Dispecer Personal – Carpatica Feroviar

O singură aplicație simplă, pe module, care înlocuiește lucrul în paralel în
**Comandă personal**, **SIT** și **RCC**, legată de **Mersul Trenurilor** și **InfoRU**.

| Cine | Unde | Ce face |
|---|---|---|
| Dispecer | `http://<server>:8780/` | hartă live cu trenurile, orele lucrate ale fiecărui mecanic/ajutor, cereri de înlocuire, pontaj |
| Mecanic / ajutor | `http://<server>:8780/mecanic` (pe telefon/tabletă) | „Disponibil” → primește comanda → **Accept / Refuz** (ca la Bolt/Uber) |

## Cum funcționează (automat)

1. **InfoRU** dă poziția live a fiecărui tren; **Mersul Trenurilor** dă traseul și orele.
2. Pentru fiecare om de pe tren se calculează cât a lucrat și când se termină programul (implicit 12 h).
3. Cu **3 ore înainte** de final, aplicația caută înlocuitor:
   * ia stațiile **din fața trenului, în sensul de mers**, la care trenul ajunge înainte ca echipajul actual să termine programul (ora estimată = mers + întârzierea live);
   * pentru fiecare mecanic/ajutor **disponibil** calculează distanța **domiciliu → stație** și dacă ajunge înaintea trenului;
   * **cel mai apropiat** primește comanda pe telefon (sună + vibrează). Are 90 s să accepte; dacă refuză sau nu răspunde, comanda trece automat la următorul.
   * mecanicul și ajutorul se caută separat, dar ajutorul e trimis de preferință în aceeași stație cu mecanicul.
4. Când InfoRU confirmă că trenul a ajuns în stația de schimb:
   * se **închide pontajul** echipajului vechi (ora reală de sosire) → intră în odihnă;
   * se **deschide pontajul** noului echipaj pe numărul trenului, de la ora reală.
5. La sosirea trenului la destinație se închide pontajul. Pontajul se exportă CSV (RCC) și se trimite automat către RCC când e conectat.

Dacă nu există nimeni disponibil, cererea devine roșie la dispecer, care poate alege manual din lista de candidați (sortată după distanță).

## Pornire

```
start_windows.bat        (Windows)
./start.sh               (Linux / macOS)
```

Implicit rulează pe **simulator** (8 trenuri de marfă pe rute reale, 60 de oameni, ceas accelerat ×60) ca să se vadă tot fluxul.
* Dispecer: parola `dispecer`
* Mecanici: ID `M001`…`M030`, ajutori `A001`…`A030`, PIN `1234`
* În simulator, oamenii care nu au aplicația deschisă răspund singuri la oferte (80% acceptă). Dacă intri cu un ID în `/mecanic`, răspunzi tu.

Ca să fie accesibilă de pe telefoane în rețea: `DISPECER_HOST=0.0.0.0` înainte de pornire.

## Date reale direct din Comandă Personal (fără proxy) – doar citire

Aplicația se loghează singură în CmdPers (`http://10.0.0.11/cmdpers_carpatica/`, iar dacă nu răspunde,
`http://10.40.0.1/cmdpers_carpatica/`) și se reloghează singură când expiră sesiunea. Nu mai e nevoie de `laptop_proxy.py`.

1. Copiați `cmdpers.example.json` în `cmdpers.json` și puneți utilizatorul și parola
   (fișierul nu se urcă pe GitHub; se pot da și prin `CMDPERS_USER` / `CMDPERS_PASS`, sau sunt cerute la pornire).
   Ideal: un cont separat, doar cu drept de citire.
2. `CmdPers-Test.bat` – verifică logarea pe ambele servere.
3. `CmdPers-Exploreaza.bat` – parcurge meniurile aplicației și scrie `date-reale/explorare/raport.md`:
   pentru fiecare pagină formularele de căutare, coloanele tabelelor și apelurile AJAX, cu ★ la cele despre
   mecanici, activități, comenzi, pontaj. **Raportul nu conține date personale** – pe el se face legătura cu mecanicii.
   Paginile complete rămân doar local, în `explorare/pagini/`.
4. `CmdPers-Mecanici.bat` – salvează local (JSON) tabelele din paginile de mecanici găsite.
5. Rulare live, în umbră: `config.json` → `{"sursa": "cmdpers_live"}`. Pozițiile vin direct din CmdPers la fiecare minut
   și se salvează și în `date-reale/locatii/`, ca ziua să poată fi reluată (`"sursa": "cmdpers"`).
   `CmdPers-Inregistreaza.bat` doar înregistrează, fără să pornească aplicația.

**Garda de doar-citire** (`app/cmdpers.py`): orice pagină se poate deschide (GET), dar POST pleacă doar spre acțiuni
de căutare (`Get…`, `Search…`, `Cauta…`) și niciodată spre ceva ce conține Save / Delete / Create / Update / Edit /
Set / Aproba / Trimite / LogOff etc. Exploratorul nu urmează nici linkurile de acest fel. Cererea e blocată înainte
să plece, deci nu poate ajunge în producție.

Din poziții aplicația deduce singură: trecerile prin stații (traseul trece la < 3 km de stație),
direcția de mers, viteza medie și stațiile din față cu ora estimată – deci merge și fără mersul trenurilor.
Până legăm mecanicii din CmdPers se pot pune manual `date-reale/personal.json` și `date-reale/echipaje.json`.

## Test cu date reale în formatul complet

Scriptul de pe TV wall (care are deja acces la InfoFer și la Comandă) poate **înregistra**
ce vede într-un dosar; aplicația **doar citește** dosarul și rulează în paralel, „în umbră”.

1. Pe TV wall: în `instrumente/inregistreaza.py` se leagă cele 4 funcții `citeste_*` de scriptul existent
   (doar citiri) și se pornește: `python inregistreaza.py --dosar date-reale --interval 60`.
   Exemplu complet de format: `python instrumente/exemplu_din_simulator.py date-exemplu`.
2. Se copiază dosarul `date-reale` lângă aplicație și se verifică: `python -m app.verifica date-reale`.
3. `config.json`: `{"sursa": "fisiere", "fisiere": {"dosar": "date-reale", "reluare": true}}` și se pornește aplicația.
   Cu `reluare: true` ziua înregistrată se derulează accelerat; cu `false` se citește mereu ultimul instantaneu (aproape live).

Ce garantează că producția nu e atinsă:
* în modul `fisiere` aplicația **nu face nicio cerere în rețea** spre sisteme (verificat în teste);
* comenzile pe care le-ar fi dat și pontajul calculat se scriu doar local, în `date-reale/iesire/`
  (`comenzi_propuse.jsonl`, `pontaj_calculat.jsonl`) – ca să le comparați cu ce s-a făcut de fapt;
* nimeni nu primește notificări: oamenii „răspund” automat, simulat; baza de date e doar în memorie;
* `doar_citire: true` (implicit) blochează scrierile și în modul `http`.

## Configurare

Copiază `config.example.json` în `config.json` și modifică ce trebuie:

| Cheie | Implicit | Ce înseamnă |
|---|---|---|
| `sursa` | `simulator` | `cmdpers_live` = direct din CmdPers (doar citire), `cmdpers` = poziții înregistrate din CmdPers, `fisiere` = date reale în formatul complet, `http` = sistemele reale |
| `doar_citire` | `true` | nu trimite nimic spre sistemele externe |
| `program_max_ore` | 12 | durata maximă a programului |
| `alerta_inainte_ore` | 3 | când începe căutarea înlocuitorului |
| `odihna_ore` | 12 | odihna după program |
| `marja_predare_min` | 15 | schimbul se face cu cel puțin atât înainte de final |
| `viteza_deplasare_kmh`, `pregatire_min` | 60, 30 | estimarea drumului de acasă la gară |
| `raza_max_km` | 250 | nu se caută oameni mai departe |
| `oferta_expira_sec` | 90 | timp de răspuns la comandă |
| `parola_dispecer` | `dispecer` | **schimbați-o** |

## Module

```
app/
  integrations/      ← câte un adaptor pe sistem (Mersul Trenurilor, InfoRU, Comandă personal/SIT/RCC)
    simulator.py       date demo
    fisiere.py         date reale înregistrate (doar citire)
    locatii.py         poziții locomotive din CmdPers → treceri prin stații, direcție, stații în față
    http_adapters.py   conectarea la sistemele reale
  cmdpers.py         ← client CmdPers: autologin, 2 servere, gardă doar-citire, explorator
  matching.py        ← alegerea celui mai apropiat om / stației de schimb
  engine.py          ← motorul: ore lucrate, alerte, oferte, schimb, pontaj automat
  main.py            ← API + pagini
  static/            ← dispecer.html (desktop), mecanic.html (telefon)
```

## Teste

```
pip install pytest httpx
python -m pytest -q
```
