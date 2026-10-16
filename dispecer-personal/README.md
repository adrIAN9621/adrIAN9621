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

## Test cu date reale, fără să atingem producția

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
| `sursa` | `simulator` | `fisiere` = date reale înregistrate (test), `http` = sistemele reale (vezi INTEGRARE.md) |
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
    http_adapters.py   conectarea la sistemele reale
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
