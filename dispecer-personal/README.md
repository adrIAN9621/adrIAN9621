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

## Configurare

Copiază `config.example.json` în `config.json` și modifică ce trebuie:

| Cheie | Implicit | Ce înseamnă |
|---|---|---|
| `sursa` | `simulator` | `http` = sistemele reale (vezi INTEGRARE.md) |
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
