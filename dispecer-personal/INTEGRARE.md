# Conectarea la sistemele reale

Aplicația citește datele prin trei adaptoare (`app/integrations/http_adapters.py`).
Setați în `config.json`:

```json
{
  "sursa": "http",
  "http": {
    "mers_trenuri_url": "https://.../api",
    "inforu_url": "https://.../api",
    "personal_url": "https://.../api",
    "token": "…",
    "timeout_sec": 10
  }
}
```

Mai jos e formatul JSON pe care îl așteaptă aplicația. Dacă sistemele voastre au alt
format (sau doar export CSV / bază de date), se schimbă **doar** maparea din adaptorul
respectiv – motorul, regulile și interfețele rămân la fel. Codurile de stație trebuie
să existe în `app/geo.py` (cod → nume, lat, lon); lista se extinde cu nomenclatorul CFR.

## 1. Mersul Trenurilor – `GET /trenuri?data=YYYY-MM-DD`

```json
[{ "tren": "50421", "tip": "marfă",
   "opriri": [
     { "statie": "BN", "sosire": null,                  "plecare": "2026-10-16T08:00:00" },
     { "statie": "BV", "sosire": "2026-10-16T11:10:00", "plecare": "2026-10-16T11:20:00" },
     { "statie": "AR", "sosire": "2026-10-16T20:40:00", "plecare": null }
   ] }]
```

## 2. InfoRU – `GET /pozitie/{tren}`

```json
{ "lat": 45.66, "lon": 25.61, "intarziere_min": 12, "viteza_kmh": 54,
  "stare": "in_mers",               // neplecat | in_mers | in_statie | sosit
  "index_ultima_statie": 4,         // poziția în lista de opriri a ultimei stații atinse
  "treceri": { "BN": "2026-10-16T08:03:00", "BV": "2026-10-16T11:22:00" } }
```
`treceri` (ora reală de sosire/trecere pe stație) e ce declanșează schimbul și pontajul.

## 3. Comandă personal / SIT / RCC

| Metodă | Cale | Conținut |
|---|---|---|
| GET | `/personal` | `[{ "id", "nume", "rol": "mecanic"/"ajutor", "telefon", "localitate", "lat", "lon", "pin" }]` – `lat/lon` = domiciliul |
| GET | `/echipaje` | `[{ "tren", "id_personal", "rol", "inceput": ISO, "statie" }]` – cine e acum pe tren |
| POST | `/comenzi` | `{ "tren", "id_personal", "rol", "statie", "ora" }` – trimis la acceptarea comenzii |
| POST | `/pontaj` | `{ "tren", "id_personal", "nume", "rol", "inceput", "statie_inceput", "sfarsit", "statie_sfarsit", "ore", "km_deplasare", "min_deplasare", "sursa" }` – trimis la închiderea fiecărei ture |

## Ce e nevoie de la voi pentru conectare

* acces (URL + cont/token) sau documentația API pentru InfoRU, Mersul Trenurilor, Comandă personal, SIT, RCC – sau măcar un export (CSV/Excel/SQL) ca să fac maparea;
* lista personalului cu adresa de domiciliu (se convertește în coordonate);
* regulile interne exacte: durata maximă a programului, odihna, autorizări (tip locomotivă, secții de remorcare) – se adaugă ca filtre în `matching.py`.
