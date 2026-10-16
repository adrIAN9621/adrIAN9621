"""Client pentru InfoRU / OTF Infofer (trenurile Carpatica în circulație) – DOAR CITIRE.

Pagina cu datele: https://otf.infofer.ro/CarpaticaFeroviarSA/TrenuriCirculatie_InParcurs
Logarea poate trece prin poarta Citrix/NetScaler https://auth.infofer.ro/vpn/tmindex.html.

  * autologin: formularul de logare al paginii (dacă are unul) sau poarta NetScaler
  * O SINGURĂ încercare de logare per pornire – dacă parola e greșită nu reîncearcă
    (contul nu se blochează); dacă se cere cod suplimentar (SMS/token) spune asta și se oprește
  * gardă de doar-citire: doar GET/POST, doar spre gazdele din inforu.json; POST doar spre
    formularul de logare găsit și spre acțiuni de citire (…_Read, Get…, Search…)

Comenzi (din dosarul dispecer-personal):

    python -m app.inforu test           logare + câte trenuri și ce coloane vede
    python -m app.inforu explora        raport cu structura paginii (fără date) pentru legarea în aplicație
    python -m app.inforu inregistreaza  salvează trenurile în circulație la fiecare 2 minute (pentru teste)
"""
from __future__ import annotations

import getpass
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional

from .cmdpers import INTERZIS, UA, LoginEsuat, Refuzat, _decodat, ajax_urls, csrf_token, parse_page

ADRESA = "https://otf.infofer.ro/CarpaticaFeroviarSA/TrenuriCirculatie_InParcurs"
POARTA = "https://auth.infofer.ro"
CONFIG = Path(__file__).resolve().parent.parent / "inforu.json"

# acțiuni de citire acceptate la POST (grilele Kendo/DataTables cer datele prin POST)
POST_CITIRE = re.compile(r"(_Read|/Read[A-Za-z]*|/(Get|Search|Cauta|Find|List|Load)[A-Za-z_]*)$", re.I)
POST_COMPUS = re.compile(r"(And|Then|Si|Apoi)[A-Z]")
NETSCALER_LOGIN = ("/cgi/login", "/nf/auth/doAuthentication.do")
USER_NAMES = ("username", "user", "login", "email", "utilizator", "userid", "user_name", "txtusername")
OTP_HINT = re.compile(r"(otp|passwd1|token|cod|code|2fa|mfa|second)", re.I)


class _Redirect(urllib.request.HTTPRedirectHandler):
    """Urmează redirecturile doar spre gazdele permise (parola / cookie-urile nu pleacă în altă parte)."""

    def __init__(self, allowed: set[str]):
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(urllib.parse.urljoin(req.full_url, newurl)) not in self.allowed:
            raise Refuzat(f"Redirect spre server necunoscut refuzat: {urllib.parse.urlsplit(newurl).netloc}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _LoginForm(HTMLParser):
    """Găsește formularul care are un câmp de parolă (cu câmpurile ascunse și valorile lor)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms: list[dict] = []
        self._f: Optional[dict] = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "form":
            self._f = {"action": a.get("action", ""), "method": a.get("method", "get").upper(), "inputs": []}
        elif tag == "input" and self._f is not None and a.get("name"):
            self._f["inputs"].append((a["name"], a.get("type", "text").lower(), a.get("value", "")))

    def handle_endtag(self, tag):
        if tag == "form" and self._f is not None:
            self.forms.append(self._f)
            self._f = None


def login_form(text: str) -> Optional[dict]:
    p = _LoginForm()
    p.feed(text)
    for f in p.forms:
        if any(t == "password" for _, t, _ in f["inputs"]):
            return f
    return None


def load_config(path: Path = CONFIG) -> dict:
    cfg = {"adresa": ADRESA, "poarta": POARTA, "utilizator": "", "parola": "", "timeout_sec": 30}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in data.items() if v not in ("", None)})
    return cfg


def _origin(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    return f"{u.scheme}://{u.netloc}".lower()


class InfoRU:
    def __init__(self, user: str, password: str, adresa: str = ADRESA, poarta: str = POARTA, timeout: float = 30):
        if not user or not password:
            raise LoginEsuat("Lipsesc utilizatorul / parola InfoRU (rulați Configureaza-Parole.bat).")
        self.user, self.password = user, password
        self.adresa, self.poarta = adresa, poarta.rstrip("/")
        self.timeout = timeout
        self.allowed = {_origin(adresa), _origin(poarta)}
        self.login_post: set[str] = set()       # formularele de logare găsite – singurele POST-uri non-citire
        self.logat = False
        self.incercat = False                   # o singură încercare de logare per pornire
        self.pasi: list[str] = []               # jurnalul logării (fără parole) – pentru raport
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar),
                                                  _Redirect(self.allowed))

    # ------------------------------------------------------------ HTTP de bază
    def _verifica(self, method: str, url: str) -> None:
        u = urllib.parse.urlsplit(url)
        path, query = _decodat(u.path), _decodat(u.query)
        if method not in ("GET", "POST"):
            raise Refuzat(f"Metodă interzisă (doar citire): {method}")
        if _origin(url) not in self.allowed:
            raise Refuzat(f"Server necunoscut (doar cele din inforu.json): {u.netloc}")
        if ".." in path.split("/") or "\\" in path or ";" in path:
            raise Refuzat(f"Cale suspectă: {path}")
        if method == "POST" and url.split("?")[0] in self.login_post:
            return
        if method == "GET" and url.lower().startswith(self.poarta.lower() + "/cgi/setclient"):
            return  # alegerea „acces din browser” pe poarta NetScaler – ține doar de sesiune
        if INTERZIS.search(path) or INTERZIS.search(query):
            raise Refuzat(f"{method} blocat (doar citire): {path}")
        last = path.rstrip("/").rsplit("/", 1)[-1]
        if method == "POST" and (not POST_CITIRE.search(path.rstrip("/")) or POST_COMPUS.search(last)):
            raise Refuzat(f"POST blocat (doar citire): {path}")

    def _raw(self, method: str, url: str, data: Optional[dict] = None, ajax: bool = False,
             referer: Optional[str] = None) -> tuple[int, str, str, str]:
        """→ (status, url final, content-type, text)"""
        self._verifica(method, url)
        body = urllib.parse.urlencode(data or {}, doseq=True).encode() if method == "POST" else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("User-Agent", UA)
        req.add_header("Accept", "application/json, text/html;q=0.9, */*;q=0.8")
        req.add_header("Accept-Language", "ro-RO,ro;q=0.9")
        if body is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
        if ajax:
            req.add_header("X-Requested-With", "XMLHttpRequest")
        if referer:
            req.add_header("Referer", referer)
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                charset = r.headers.get_content_charset() or "utf-8"
                text = r.read().decode(charset, errors="replace")
                status, final, ct = r.status, r.geturl(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            status, final, ct = e.code, e.geturl(), e.headers.get("Content-Type", "") if e.headers else ""
            text = e.read().decode("utf-8", errors="replace") if e.fp else ""
        self.pasi.append(f"{method} {urllib.parse.urlsplit(url).netloc}{urllib.parse.urlsplit(url).path} → "
                         f"{status} {urllib.parse.urlsplit(final).netloc}{urllib.parse.urlsplit(final).path}")
        return status, final, ct, text

    @staticmethod
    def _cere_logare(final: str, text: str) -> bool:
        return (login_form(text) is not None or "/vpn/" in final.lower() or "/logon/" in final.lower()
                or "tmindex" in final.lower())

    # ------------------------------------------------------------------ login
    def login(self) -> None:
        if self.incercat and not self.logat:
            raise LoginEsuat("Logarea InfoRU a eșuat deja – nu mai reîncerc automat (verificați parola și reporniți).")
        self.incercat = True
        status, final, _, text = self._raw("GET", self.adresa)
        if status < 400 and not self._cere_logare(final, text):
            self.logat = True
            return
        form = login_form(text)
        if form is not None:
            self._form_login(form, final)
        else:
            self._netscaler_login()
        status, final, _, text = self._raw("GET", self.adresa)
        if status >= 400 or self._cere_logare(final, text):
            f = login_form(text)
            if f and any(OTP_HINT.search(n) for n, t, _ in f["inputs"] if t in ("password", "text", "number")):
                raise LoginEsuat("InfoRU cere un cod suplimentar (SMS/token) – autologinul nu poate trece de el.")
            raise LoginEsuat("Logare InfoRU eșuată – utilizator / parolă greșite sau altă metodă de logare "
                             "(rulați „python -m app.inforu explora” și trimiteți raportul).")
        self.logat = True

    def _form_login(self, form: dict, page_url: str) -> None:
        action = urllib.parse.urljoin(page_url, form["action"] or page_url).split("#")[0]
        data, user_set = {}, False
        for name, typ, value in form["inputs"]:
            if typ == "password":
                data[name] = self.password
            elif typ in ("text", "email") and not user_set and (
                    name.lower() in USER_NAMES or not any(n.lower() in USER_NAMES for n, _, _ in form["inputs"])):
                data[name], user_set = self.user, True
            elif typ in ("hidden",):
                data[name] = value
            elif typ == "checkbox":
                continue
            elif typ == "submit" and value:
                data[name] = value
        token = csrf_token(" ".join(f'name="{n}" value="{v}"' for n, t, v in form["inputs"] if t == "hidden"))
        if token:
            data.setdefault("__RequestVerificationToken", token)
        self.login_post.add(action.split("?")[0])
        self._raw("POST", action, data, referer=page_url)

    def _netscaler_login(self) -> None:
        """Poarta Citrix NetScaler (pagina de logare e desenată din JavaScript, deci nu are <form>)."""
        url = self.poarta + NETSCALER_LOGIN[0]
        self.login_post.update(self.poarta + p for p in NETSCALER_LOGIN)
        status, final, _, _ = self._raw("POST", url, {"login": self.user, "passwd": self.password},
                                        referer=self.poarta + "/vpn/tmindex.html")
        if status in (404, 405, 501):  # interfața nouă RfWebUI – doar dacă cea veche nu există
            self._raw("POST", self.poarta + NETSCALER_LOGIN[1], {
                "login": self.user, "passwd": self.password, "savecredentials": "false",
                "nsg-x1-logon-button": "Log On", "StateContext": ""}, ajax=True,
                referer=self.poarta + "/logon/LogonPoint/tmindex.html")
        # alegerea „acces din browser” (clientless), dacă poarta o cere
        for p in ("/cgi/setclient?cvpn",):
            try:
                self._raw("GET", self.poarta + p)
            except Refuzat:
                pass

    def get_page(self) -> tuple[str, str]:
        if not self.logat:
            self.login()
        status, final, ct, text = self._raw("GET", self.adresa)
        if self._cere_logare(final, text):  # sesiunea a expirat: o singură relogare
            self.logat, self.incercat = False, False
            self.login()
            status, final, ct, text = self._raw("GET", self.adresa)
        return final, text

    # -------------------------------------------------------------- date
    def trenuri(self) -> tuple[list[str], list[dict]]:
        """→ (coloane, rânduri) din tabelul paginii sau din grila încărcată prin AJAX."""
        final, text = self.get_page()
        page = parse_page(text)
        best = max(page.tables, key=lambda t: len(t["rows"]), default=None)
        if best and best["rows"]:
            rows = best["rows"]
            cols = best["headers"]
            if not cols and any(c.strip().lower() == "tren" for c in rows[0]):
                cols, rows = rows[0], rows[1:]  # antetul e scris cu <td>, nu <th>
            cols = cols or [f"col{i + 1}" for i in range(len(rows[0]))]
            return cols, [dict(zip(cols, r)) for r in rows if len(r) >= len(cols) // 2]
        token = csrf_token(text)
        for u in ajax_urls_any(page, final):
            if not POST_CITIRE.search(urllib.parse.urlsplit(u).path):
                continue
            try:
                _, _, _, body = self._raw("POST", u, {"__RequestVerificationToken": token} if token else {},
                                          ajax=True, referer=final)
            except Refuzat:
                continue
            rows = _rows_from_json(body)
            if rows:
                return list(rows[0].keys()), rows
        return [], []


def ajax_urls_any(page, base: str) -> list[str]:
    """URL-urile AJAX din scripturile paginii, absolute (pentru orice aplicație, nu doar CmdPers)."""
    out = set()
    pat = re.compile(r"""["']((?:https?://[^"'\s]+)?/[A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-]+)+)["']""")
    for s in page.scripts:
        for m in pat.finditer(s):
            out.add(urllib.parse.urljoin(base, m.group(1)))
    out.update(urllib.parse.urljoin(base, u) for u in ajax_urls(page) if not u.startswith("/cmdpers"))
    return sorted(out)


def _rows_from_json(body: str) -> list[dict]:
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return []
    if isinstance(data, dict):
        for k in ("Data", "data", "rows", "Rows", "items", "Items", "aaData", "result", "Result"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def from_config(path: Path = CONFIG, ask: bool = False) -> InfoRU:
    cfg = load_config(path)
    if ask and not cfg["utilizator"]:
        cfg["utilizator"] = input("Utilizator InfoRU: ").strip()
    if ask and not cfg["parola"]:
        cfg["parola"] = getpass.getpass("Parolă InfoRU: ")
    return InfoRU(cfg["utilizator"], cfg["parola"], cfg["adresa"], cfg["poarta"], cfg["timeout_sec"])


# ================================================================ explorare
def explore(ir: InfoRU, out: Path) -> Path:
    """Raport cu structura paginii (fără date): pașii logării, formulare, coloane, apeluri AJAX,
    câmpurile din răspunsurile JSON. Pagina completă rămâne local în `out/pagina.html`."""
    out.mkdir(parents=True, exist_ok=True)
    lines = [f"# Structura InfoRU – {datetime.now():%d.%m.%Y %H:%M}", ""]
    try:
        final, text = ir.get_page()
    except Exception as e:
        lines += [f"**Logare eșuată:** {e}", "", "## Pașii logării", *[f"- {p}" for p in ir.pasi]]
        (out / "raport.md").write_text("\n".join(lines), encoding="utf-8")
        return out / "raport.md"
    (out / "pagina.html").write_text(text, encoding="utf-8")
    page = parse_page(text)
    lines += [f"Pagina: `{urllib.parse.urlsplit(final).path}` – {page.title.strip()}", "", "## Pașii logării",
              *[f"- {p}" for p in ir.pasi], "", "## Tabele"]
    for t in page.tables:
        lines.append(f"- `{t['id']}`: {' | '.join(t['headers']) or '(fără antet)'} – {len(t['rows'])} rânduri")
    lines += ["", "## Formulare"]
    for f in page.forms:
        lines.append(f"- {f['method']} `{f['action']}`: {', '.join(f['fields']) or '–'}")
    lines += ["", "## Apeluri AJAX"]
    token = csrf_token(text)
    for u in ajax_urls_any(page, final):
        info = ""
        if POST_CITIRE.search(urllib.parse.urlsplit(u).path) and _origin(u) in ir.allowed:
            try:
                st, _, ct, body = ir._raw("POST", u, {"__RequestVerificationToken": token} if token else {},
                                          ajax=True, referer=final)
                rows = _rows_from_json(body)
                info = f" → {st}, {len(rows)} rânduri, câmpuri: {', '.join(rows[0].keys()) if rows else '–'}"
            except Refuzat as e:
                info = f" → blocat: {e}"
            except Exception as e:
                info = f" → eroare: {e}"
            time.sleep(1)
        lines.append(f"- `{urllib.parse.urlsplit(u).path}`{info}")
    (out / "raport.md").write_text("\n".join(lines), encoding="utf-8")
    return out / "raport.md"


def _record(ir: InfoRU, folder: Path, interval: int) -> None:
    d = folder / "inforu"
    d.mkdir(parents=True, exist_ok=True)
    interval = max(interval, 60)
    print(f"Înregistrez trenurile în circulație → {d.resolve()}  (Ctrl+C pentru oprire)")
    while True:
        acum = datetime.now().replace(microsecond=0)
        try:
            cols, rows = ir.trenuri()
            path = d / f"{acum:%Y-%m-%dT%H-%M-%S}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"ora": acum.isoformat(), "coloane": cols, "trenuri": rows},
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
            print(acum, f"salvat {len(rows)} trenuri")
        except LoginEsuat as e:
            print(acum, "STOP:", e)
            return
        except Exception as e:  # o citire ratată nu oprește înregistrarea
            print(acum, "eroare:", e)
        time.sleep(interval)


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "test"
    if cmd not in ("test", "explora", "inregistreaza"):
        print(__doc__)
        return 1
    ir = from_config(ask=True)
    folder = Path(argv[1]) if len(argv) > 1 else Path("date-reale")
    try:
        if cmd == "test":
            cols, rows = ir.trenuri()
            print(f"OK – logat. {len(rows)} trenuri în circulație.")
            print("Coloane:", " | ".join(cols) or "(nu am găsit tabelul – rulați InfoRU-Exploreaza.bat)")
        elif cmd == "explora":
            print("Raport:", explore(ir, folder / "explorare-inforu"))
        else:
            _record(ir, folder, int(argv[2]) if len(argv) > 2 else 120)
    except LoginEsuat as e:
        print("EȘEC:", e)
        print("Pașii logării:", *ir.pasi, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


# ================================================== tabelul „Trenuri în parcurs”
def _ora(v: Any) -> Optional[float]:
    s = str(v or "").strip()
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            pass
    return None


def _col(row: dict, *names: str) -> str:
    low = {str(k).strip().lower(): v for k, v in row.items()}
    for n in names:
        if n.lower() in low:
            return str(low[n.lower()] or "").strip()
    return ""


def normalizeaza(row: dict) -> Optional[dict]:
    """Un rând din „Trenuri în circulație – În parcurs” → câmpuri pentru aplicație.

    Tren „58428016/” = trenul 584280 plecat în ziua 16 a lunii. S / P = M (raportat) sau
    E (estimat) pentru Sosire / Plecare-Trecere. Min = întârzierea (negativ = în avans).
    """
    raw = _col(row, "Tren", "NrTren").rstrip("/").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 3:
        return None
    rel = _col(row, "Relatia", "Relația")
    # „Moacsa hcv -Curtici”, „Constanta Port Zona C -Dornesti”: separatorul e „-” lângă un spațiu,
    # iar dacă lipsește (Brazi-Bacau) primul „-”
    m = re.search(r"\s-|-\s", rel)
    cut = m.start() if m else rel.find("-")
    orig, dest = (rel[:cut], rel[cut:].lstrip(" -")) if cut >= 0 else (rel, "")
    s_flag, p_flag = _col(row, "S").upper(), _col(row, "P").upper()
    sosire, plecare = _ora(_col(row, "Sosire")), _ora(_col(row, "Plecare/Trecere", "Plecare"))
    try:
        intarziere = float(_col(row, "Min") or 0)
    except ValueError:
        intarziere = 0.0
    real = [t for t, f in ((plecare, p_flag), (sosire, s_flag)) if t and f == "M"]
    return {
        "id": digits,                                   # cheia unică (tren + zi)
        "tren": digits[:-2] if len(digits) > 6 else digits,
        "zi": digits[-2:] if len(digits) > 6 else "",
        "rang": _col(row, "Rang"),
        "origine": orig.strip(), "destinatie": dest.strip(),
        "statie": _col(row, "Raportat"),
        "sosire": sosire, "sosire_reala": s_flag == "M",
        "plecare": plecare, "plecare_reala": p_flag == "M",
        "ora_raportare": max(real) if real else None,
        "intarziere_min": intarziere,
        "trasa": _col(row, "Identificator trasa"),
    }
