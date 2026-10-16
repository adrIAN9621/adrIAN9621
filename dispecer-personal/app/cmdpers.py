"""Client direct pentru Comandă Personal (CmdPers) – fără laptop_proxy, DOAR CITIRE.

  * autologin cu utilizator + parolă (din cmdpers.json, variabile de mediu sau întrebat la pornire)
  * încearcă serverele pe rând: http://10.0.0.11, apoi http://10.40.0.1
  * se reloghează singur când sesiunea expiră
  * gardă de siguranță: GET oriunde, dar POST DOAR spre acțiuni de căutare/citire
    (GetLatestLocation, Search…, Get…) – orice altceva e refuzat înainte să plece cererea

Comenzi (rulate din dosarul dispecer-personal):

    python -m app.cmdpers test          verifică logarea pe fiecare server
    python -m app.cmdpers locatii       pozițiile locomotivelor acum
    python -m app.cmdpers explora       caută prin aplicație paginile cu mecanici / activități / comenzi
    python -m app.cmdpers mecanici      salvează tabelele din paginile de mecanici (JSON local)
    python -m app.cmdpers comenzi       comenzile active (ActiveOrders): cine e comandat pe ce tren
    python -m app.cmdpers inregistreaza înregistrează pozițiile la fiecare minut (pentru teste)
"""
from __future__ import annotations

import getpass
import html
import http.cookiejar
import json
import os
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

BASE_PATH = "/cmdpers_carpatica"
SERVERS = ["http://10.0.0.11", "http://10.40.0.1"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DispecerPersonal/1.0 (doar citire)"
CONFIG = Path(__file__).resolve().parent.parent / "cmdpers.json"

# POST e permis doar pentru acțiuni care citesc; cuvintele interzise câștigă mereu.
# Ruta trebuie să fie exact /cmdpers_carpatica/{controller}/{acțiune} – fără segment {id}, altfel
# /Comanda/Accept/GetData ar trece (în ASP.NET MVC acțiunea e Accept, „GetData” e doar id-ul).
POST_PERMIS = re.compile(rf"^{BASE_PATH}/[A-Za-z]+/(Get|Search|Cauta|Find|List|Load|Read)[A-Za-z]*$", re.I)
# acțiuni compuse (GetAndAccept, LoadThenSave) – refuzate la POST
POST_COMPUS = re.compile(r"(And|Then|Si|Apoi)[A-Z]")
LOGIN_PATH = BASE_PATH + "/Account/Login"
# Verificat pe cale + query, după decodarea %xx, pentru ORICE cerere (și GET – unele aplicații
# ASP.NET modifică date și pe GET, ex. /Comanda/Accept?id=5). Mai bine o pagină sărită decât o scriere.
INTERZIS = re.compile(
    r"(save|salv|delete|sterg|update|actualiz|create|creea|add|adaug|edit|insert|set|remove|move|muta|"
    r"approve|aproba|accept|confirm|reject|respinge|refuz|assign|asign|aloca|valid|inchide|close|"
    r"finaliz|finish|complete|generate|genere|submit|trimit|send|emit|publish|import|upload|"
    r"logoff|logout|signout|sign|semn|deconect|reset|change|schimb|inlocu|replace|modif|anul|cancel|"
    r"lock|toggle|mark|clear|dismiss|activate|activeaz|deactiv|dezactiv|archiv|arhiv|restore|restaur|"
    r"execut|ruleaz|process|proces|register|inregistr|sync|sincron|ponteaz|start|stop|porneste|opreste|"
    r"switch|impersonat|copy|copiaz|clone|duplic|write|apply)", re.I)
# pagini interesante pentru dispecerat
INTERESANT = re.compile(r"(engineer|mecanic|personal|employee|angajat|comand|order|activit|pontaj|"
                        r"timesheet|schedule|program|tura|shift|crew|echipaj|train|tren|locomotiv)", re.I)

TOKEN_PATTERNS = [
    r'name="__RequestVerificationToken"[^>]*value="([^"]+)"',
    r'value="([^"]+)"\s+name="__RequestVerificationToken"',
    r'__RequestVerificationToken[^>]*value="([^"]+)"',
    r'"__RequestVerificationToken"\s*:\s*"([^"]+)"',
]


class Refuzat(Exception):
    """Cerere blocată de garda de doar-citire."""


class LoginEsuat(Exception):
    pass


def _decodat(s: str) -> str:
    """Decodează %xx de mai multe ori (%2553 → %53 → S), ca serverul să nu vadă altceva decât garda."""
    for _ in range(5):
        d = urllib.parse.unquote_plus(s)
        if d == s:
            break
        s = d
    return s


def csrf_token(text: str) -> str:
    for pat in TOKEN_PATTERNS:
        m = re.search(pat, text)
        if m:
            return html.unescape(m.group(1))
    return ""


def load_config(path: Path = CONFIG) -> dict:
    cfg = {"servere": SERVERS, "utilizator": "", "parola": "", "timeout_sec": 30}
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    cfg["utilizator"] = os.environ.get("CMDPERS_USER", cfg["utilizator"])
    cfg["parola"] = os.environ.get("CMDPERS_PASS", cfg["parola"])
    return cfg


class CmdPers:
    def __init__(self, user: str, password: str, servers: list[str] = SERVERS, timeout: float = 30):
        if not user or not password:
            raise LoginEsuat("Lipsesc utilizatorul / parola CmdPers (cmdpers.json sau CMDPERS_USER / CMDPERS_PASS).")
        self.user, self.password = user, password
        self.servers = [s.rstrip("/") for s in servers]
        self.timeout = timeout
        self.server: Optional[str] = None
        # după „parolă greșită” nu mai reîncercăm automat (contul s-ar putea bloca în AD)
        self.credentiale_gresite = False
        self.jar = http.cookiejar.CookieJar()
        # ProxyHandler({}) = conexiune directă în rețeaua internă, fără proxy-uri de sistem
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                  urllib.request.HTTPCookieProcessor(self.jar))

    # ------------------------------------------------------------ HTTP de bază
    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        if not path.startswith(BASE_PATH):
            path = BASE_PATH + ("" if path.startswith("/") else "/") + path
        return self.server + path

    def _verifica(self, method: str, url: str) -> None:
        """Garda de doar-citire – ridică Refuzat înainte să plece cererea."""
        u = urllib.parse.urlsplit(url)  # urlsplit păstrează „;…” în cale (urlparse l-ar ascunde în params)
        path, query = _decodat(u.path), _decodat(u.query)
        if method not in ("GET", "POST"):
            raise Refuzat(f"Metodă interzisă (doar citire): {method}")
        if f"{u.scheme}://{u.netloc}".lower() not in [s.lower() for s in self.servers]:
            raise Refuzat(f"Server necunoscut (doar cele din configurare): {u.netloc}")
        if ".." in path.split("/") or "\\" in path or ";" in path:
            raise Refuzat(f"Cale suspectă: {path}")
        login = path.rstrip("/").lower() == LOGIN_PATH.lower()
        if login and (method == "GET" or not query):
            return
        if INTERZIS.search(path) or INTERZIS.search(query):
            raise Refuzat(f"{method} blocat (doar citire): {path}")
        if method == "POST" and (query or not POST_PERMIS.search(path.rstrip("/"))
                                 or POST_COMPUS.search(path.rstrip("/").rsplit("/", 1)[-1])):
            raise Refuzat(f"POST blocat (doar citire): {path}")

    def _raw(self, method: str, url: str, data: Optional[dict] = None, ajax: bool = False,
             referer: Optional[str] = None) -> tuple[str, str, str]:
        """→ (url final după redirect, content-type, text)"""
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
        with self.opener.open(req, timeout=self.timeout) as r:
            ct = r.headers.get("Content-Type", "")
            charset = r.headers.get_content_charset() or "utf-8"
            return r.geturl(), ct, r.read().decode(charset, errors="replace")

    # ------------------------------------------------------------------ login
    def login(self) -> str:
        errors = []
        for srv in self.servers:
            self.server = srv
            try:
                url, _, text = self._raw("GET", self._url("/Account/Login"))
                token = csrf_token(text)
                final, _, text = self._raw("POST", self._url("/Account/Login"), {
                    "UserName": self.user, "Password": self.password,
                    "__RequestVerificationToken": token, "RememberMe": "false",
                }, referer=url)
                if "/account/login" in final.lower() or 'name="Password"' in text:
                    errors.append(f"{srv}: utilizator sau parolă greșite")
                    self.credentiale_gresite = True
                    continue
                self.credentiale_gresite = False
                return srv
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                errors.append(f"{srv}: {getattr(e, 'reason', e)}")
        self.server = None
        raise LoginEsuat("Logare CmdPers eșuată – " + "; ".join(errors))

    def _relogin(self) -> None:
        if self.credentiale_gresite:
            raise LoginEsuat("Utilizator / parolă CmdPers greșite – nu mai reîncerc automat (reporniți după corectare).")
        self.login()

    def _ensure(self) -> None:
        if self.server is None:
            self._relogin()

    def request(self, method: str, path: str, data: Optional[dict] = None, ajax: bool = False,
                referer: Optional[str] = None) -> tuple[str, str, str]:
        """Cerere cu relogare automată dacă sesiunea a expirat sau serverul a căzut."""
        self._ensure()
        for attempt in range(2):
            try:
                final, ct, text = self._raw(method, self._url(path), data, ajax,
                                            self._url(referer) if referer else None)
                if "/account/login" in final.lower() and "/account/login" not in path.lower():
                    raise LoginEsuat("sesiune expirată")
                return final, ct, text
            except (LoginEsuat, urllib.error.URLError, TimeoutError, OSError):
                if attempt:
                    raise
                self.jar.clear()
                self.server = None
                self._relogin()
        raise AssertionError("unreachable")

    def get(self, path: str) -> str:
        return self.request("GET", path)[2]

    def descarca(self, path: str, referer: Optional[str] = None) -> tuple[str, bytes]:
        """GET pentru fișiere (ex. exportul Excel) – aceeași gardă, conținutul păstrat ca bytes."""
        self._ensure()
        url = self._url(path)
        self._verifica("GET", url)
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", UA)
        if referer:
            req.add_header("Referer", self._url(referer))
        with self.opener.open(req, timeout=self.timeout) as r:
            return r.headers.get("Content-Type", ""), r.read()

    def search(self, page: str, action: str, data: dict) -> Any:
        """Ca în browser: deschide pagina (pentru token CSRF) și trimite căutarea AJAX."""
        text = self.get(page)
        form = {"__RequestVerificationToken": csrf_token(text), **data}
        _, ct, body = self.request("POST", action, form, ajax=True, referer=page)
        return json.loads(body) if body.strip()[:1] in "[{" else body

    # -------------------------------------------------------------- date
    def locations(self, active_only: bool = True) -> list[dict]:
        from .integrations.locatii import parse_items
        raw = self.search("/LocomotiveLocation/Index", "/LocomotiveLocation/GetLatestLocation",
                          {"activeOnly": "true" if active_only else "false", "numarTren": "", "locomotiva": ""})
        return parse_items(raw)


    def comenzi_active(self) -> tuple[list[str], list[dict], list[str]]:
        """Comenzile active (ce mecanic / ajutor e comandat pe ce tren) din /ActiveOrders/Index.

        → (coloane, rânduri, jurnal). Tabelul e citit din pagină; dacă pagina îl încarcă separat
        (DataTables / AJAX), se încearcă cererile de citire găsite în scripturile paginii.
        """
        from .inforu import _rows_from_json
        jurnal: list[str] = []
        page_path = "/ActiveOrders/Index"
        text = self.get(page_path)
        page = parse_page(text)
        jurnal.append(f"pagina „{page.title.strip()}”: {len(page.tables)} tabele, {len(page.forms)} formulare")
        best = max(page.tables, key=lambda t: len(t["rows"]), default=None)
        if best and best["rows"]:
            rows = best["rows"]
            cols = best["headers"] or [f"col{i + 1}" for i in range(len(rows[0]))]
            return cols, [dict(zip(cols, r)) for r in rows], jurnal
        for t in page.tables:
            jurnal.append(f"tabel id=„{t['id']}”: {len(t['headers'])} coloane în antet, {len(t['rows'])} rânduri"
                          + (f" – {' | '.join(t['headers'])}" if t["headers"] else ""))
        # 1) exportul Excel din pagină (același fișier ca butonul din browser)
        for href, label in page.links:
            if re.search(r"xls|excel|export", href + " " + label, re.I):
                p = _norm_link(href, self._url(page_path))
                if not p:
                    continue
                jurnal.append(f"link export: „{label.strip()}” → {p.split('?')[0]}")
                try:
                    ct, data = self.descarca(p, referer=page_path)
                except Exception as e:
                    jurnal.append(f"  descărcare eșuată: {e}")
                    continue
                if data[:2] == b"PK":  # fișier .xlsx
                    import tempfile
                    from .comenzi_xlsx import citeste_xlsx, gaseste_antet
                    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
                        f.write(data)
                    rows = citeste_xlsx(Path(f.name))
                    Path(f.name).unlink(missing_ok=True)
                    h = gaseste_antet(rows)
                    hdr, body = rows[h], [r for r in rows[h + 1:] if any(r)]
                    jurnal.append(f"  Excel descărcat: {len(body)} rânduri")
                    return hdr, [dict(zip(hdr, r)) for r in body], jurnal
                jurnal.append(f"  nu e Excel ({ct})")
        # 2) cererea AJAX care umple tabelul – din scripturile paginii și din fișierele .js ale aplicației
        scripts_text = list(page.scripts)
        for s in page.scripts:
            if s.startswith("@src "):
                src = _norm_link(s[5:].strip(), self._url(page_path))
                if src and "jquery" not in src.lower() and "bootstrap" not in src.lower():
                    try:
                        scripts_text.append(self.get(src))
                    except Exception:
                        pass
        page.scripts = scripts_text
        found = ajax_urls(page)
        jurnal.append("URL-uri găsite în scripturi: " + (", ".join(u for u in found if "order" in u.lower()) or "–"))
        token = csrf_token(text)
        for u in found:
            path = urllib.parse.urlsplit(u).path
            if "order" not in path.lower():
                continue
            for method in ("POST", "GET"):
                try:
                    data = {"__RequestVerificationToken": token} if method == "POST" and token else None
                    _, ct, body = self.request(method, path, data, ajax=True, referer=page_path)
                except Refuzat as e:
                    jurnal.append(f"{method} {path}: blocat ({e})")
                    continue
                except Exception as e:
                    jurnal.append(f"{method} {path}: eroare {e}")
                    continue
                rows = _rows_from_json(body)
                jurnal.append(f"{method} {path}: {len(rows)} rânduri")
                if rows:
                    return list(rows[0].keys()), rows, jurnal
        if best and best["headers"]:
            jurnal.append("tabel fără rânduri (nicio comandă activă?) – coloane: " + " | ".join(best["headers"]))
            return best["headers"], [], jurnal
        return [], [], jurnal


def from_config(path: Path = CONFIG, ask: bool = False) -> CmdPers:
    cfg = load_config(path)
    if ask and not cfg["utilizator"]:
        cfg["utilizator"] = input("Utilizator CmdPers: ").strip()
    if ask and not cfg["parola"]:
        cfg["parola"] = getpass.getpass("Parolă CmdPers: ")
    return CmdPers(cfg["utilizator"], cfg["parola"], cfg["servere"], cfg["timeout_sec"])


# ===================================================================== HTML
class _Page(HTMLParser):
    """Extrage linkuri, formulare, tabele și URL-uri AJAX dintr-o pagină."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.forms: list[dict] = []
        self.tables: list[dict] = []
        self.title = ""
        self._a: Optional[list] = None
        self._form: Optional[dict] = None
        self._tbl: Optional[dict] = None
        self._row: Optional[list] = None
        self._cell: Optional[list] = None
        self._in_title = False
        self.scripts: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self._a = [a["href"], ""]
            # confirm(...) / data-method=post / data-ajax-confirm = buton de modificare deghizat în link
            semne = " ".join(f"{k}={v}" for k, v in attrs if k != "href" and v).lower()
            if (re.search(r"confirm\(|data-(ajax-)?confirm|btn-danger", semne + " " + " ".join(k for k, _ in attrs))
                    or (a.get("data-method") or a.get("data-ajax-method") or "get").lower() != "get"):
                self._a = None
        elif tag == "form":
            self._form = {"action": a.get("action", ""), "method": (a.get("method") or "get").upper(),
                          "id": a.get("id", ""), "fields": []}
        elif tag in ("input", "select", "textarea") and self._form is not None and a.get("name"):
            if a.get("type") not in ("hidden",) or a.get("name") != "__RequestVerificationToken":
                self._form["fields"].append(a["name"])
        elif tag == "table":
            self._tbl = {"id": a.get("id", ""), "headers": [], "rows": []}
        elif tag == "tr" and self._tbl is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = [tag, ""]
        elif tag == "title":
            self._in_title = True
        elif tag == "script":
            self._in_script = True
            if a.get("src"):
                self.scripts.append("@src " + a["src"])

    def handle_endtag(self, tag):
        if tag == "a" and self._a:
            self.links.append((self._a[0], " ".join(self._a[1].split())))
            self._a = None
        elif tag == "form" and self._form is not None:
            self.forms.append(self._form)
            self._form = None
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append((self._cell[0], " ".join(self._cell[1].split())))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._tbl is not None:
            if self._row and all(k == "th" for k, _ in self._row) and not self._tbl["headers"]:
                self._tbl["headers"] = [v for _, v in self._row]
            elif self._row:
                self._tbl["rows"].append([v for _, v in self._row])
            self._row = None
        elif tag == "table" and self._tbl is not None:
            self.tables.append(self._tbl)
            self._tbl = None
        elif tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._a is not None:
            self._a[1] += data
        if self._cell is not None:
            self._cell[1] += data
        if self._in_title:
            self.title += data
        if self._in_script:
            self.scripts.append(data)


def parse_page(text: str) -> _Page:
    p = _Page()
    p.feed(text)
    return p


AJAX_URL = re.compile(r"""["'](/cmdpers_carpatica/[A-Za-z0-9_/]+|(?:\.\./|/)?[A-Z][A-Za-z0-9]+/[A-Z][A-Za-z0-9]+)["']""")


def ajax_urls(page: _Page) -> list[str]:
    out = set()
    for s in page.scripts:
        for m in AJAX_URL.finditer(s):
            u = m.group(1)
            if not u.startswith("/cmdpers_carpatica"):
                u = BASE_PATH + "/" + u.lstrip("./")
            out.add(u)
    return sorted(out)


def _norm_link(href: str, base: str) -> Optional[str]:
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return None
    full = urllib.parse.urljoin(base, href)
    p = urllib.parse.urlparse(full)
    if not p.path.lower().startswith(BASE_PATH):
        return None
    return p.path + (("?" + p.query) if p.query else "")


# ================================================================ explorare
def explore(cp: CmdPers, out: Path, max_pages: int = 80, pauza: float = 1.0) -> Path:
    """Parcurge meniurile aplicației (doar GET, fără linkuri de modificare / logout) și scrie
    un raport cu STRUCTURA paginilor: titlu, formulare de căutare, coloanele tabelelor, URL-uri AJAX.
    Raportul nu conține date personale (doar numărul de rânduri), deci poate fi trimis mai departe.
    Paginile complete se salvează local, în `out/pagini/`, doar pentru voi."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "pagini").mkdir(exist_ok=True)
    queue = ["/", "/Home/Index", "/LocomotiveLocation/Index", "/LocomotiveEngineer/Index"]
    queue = [BASE_PATH + q if q != "/" else BASE_PATH + "/" for q in queue]
    seen: set[str] = set()
    report: list[dict] = []
    while queue and len(seen) < max_pages:
        path = queue.pop(0)
        key = path.split("?")[0].rstrip("/").lower()
        if key in seen or INTERZIS.search(_decodat(path)):
            continue
        seen.add(key)
        if len(seen) > 1:
            time.sleep(pauza)  # fără rafale spre serverul de producție
        try:
            final, ct, text = cp.request("GET", path)
        except Exception as e:
            report.append({"pagina": path, "eroare": str(e)})
            continue
        if "html" not in ct:
            continue
        page = parse_page(text)
        name = re.sub(r"[^\w]+", "_", path.strip("/")) or "index"
        (out / "pagini" / f"{name}.html").write_text(text, encoding="utf-8")
        report.append({
            "pagina": path, "titlu": page.title.strip(),
            "interesant": bool(INTERESANT.search(path) or INTERESANT.search(page.title)),
            "formulare": [{"action": f["action"], "method": f["method"], "campuri": f["fields"]} for f in page.forms],
            "tabele": [{"id": t["id"], "coloane": t["headers"], "randuri": len(t["rows"])} for t in page.tables],
            "ajax": ajax_urls(page),
        })
        for href, _text in page.links:
            n = _norm_link(href, final)
            if n and n.split("?")[0].rstrip("/").lower() not in seen and not INTERZIS.search(_decodat(n)):
                queue.append(n)
    report.sort(key=lambda r: (not r.get("interesant"), r["pagina"]))
    (out / "raport.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Structura CmdPers ({cp.server}) – {datetime.now():%d.%m.%Y %H:%M}", "",
             "Doar structura paginilor (fără date personale). Paginile marcate ★ par legate de mecanici / comenzi.", ""]
    for r in report:
        if "eroare" in r:
            lines.append(f"- {r['pagina']} – eroare: {r['eroare']}")
            continue
        lines.append(f"## {'★ ' if r['interesant'] else ''}{r['pagina']} – {r['titlu']}")
        for f in r["formulare"]:
            lines.append(f"- formular {f['method']} `{f['action']}`: {', '.join(f['campuri']) or '–'}")
        for t in r["tabele"]:
            lines.append(f"- tabel `{t['id']}`: {' | '.join(t['coloane']) or '(fără antet)'} – {t['randuri']} rânduri")
        for u in r["ajax"]:
            lines.append(f"- AJAX `{u}`")
        lines.append("")
    (out / "raport.md").write_text("\n".join(lines), encoding="utf-8")
    return out / "raport.md"


def engineer_tables(cp: CmdPers, out: Path) -> list[Path]:
    """Salvează local tabelele din paginile de mecanici/activități găsite la explorare (sau implicite)."""
    pages = ["/LocomotiveEngineer/Index"]
    rep = out / "raport.json"
    if rep.exists():
        pages = [r["pagina"] for r in json.loads(rep.read_text("utf-8"))
                 if r.get("interesant") and r.get("tabele") and re.search(r"engineer|mecanic|activit|comand|personal", r["pagina"], re.I)] or pages
    saved = []
    (out / "date").mkdir(parents=True, exist_ok=True)
    for path in pages:
        page = parse_page(cp.get(path))
        data = [{"coloane": t["headers"], "randuri": [dict(zip(t["headers"], r)) if t["headers"] else r for r in t["rows"]]}
                for t in page.tables]
        p = out / "date" / (re.sub(r"[^\w]+", "_", path.strip("/")) + ".json")
        p.write_text(json.dumps({"pagina": path, "ora": datetime.now().isoformat(), "tabele": data},
                                ensure_ascii=False, indent=1), encoding="utf-8")
        saved.append(p)
    return saved


# ===================================================================== CLI
def _record(cp: CmdPers, folder: Path, interval: int) -> None:
    d = folder / "locatii"
    d.mkdir(parents=True, exist_ok=True)
    print(f"Înregistrez pozițiile din CmdPers ({cp.server}) → {d.resolve()}  (Ctrl+C pentru oprire)")
    while True:
        acum = datetime.now().replace(microsecond=0)
        try:
            items = cp.locations()
            path = d / f"{acum:%Y-%m-%dT%H-%M-%S}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"ora": acum.isoformat(), "sursa": cp.server, "date": items},
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
            print(acum, f"salvat {len(items)} locomotive")
        except Exception as e:  # o citire ratată nu oprește înregistrarea
            print(acum, "eroare:", e)
        time.sleep(max(interval, 15))  # minim 15 s între cereri – nu încărcăm producția


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "test"
    if cmd not in ("test", "locatii", "explora", "mecanici", "inregistreaza", "comenzi"):
        print(__doc__)
        return 1
    cfg = load_config()
    if cmd == "test":
        cp = from_config(ask=True)
        for srv in cfg["servere"]:
            try:
                cp.servers = [srv]
                cp.jar.clear()
                cp.login()
                print(f"OK    {srv} – logat")
            except Exception as e:
                print(f"EȘEC  {srv} – {e}")
        return 0
    cp = from_config(ask=True)
    srv = cp.login()
    print(f"Logat pe {srv}")
    folder = Path(argv[1]) if len(argv) > 1 else Path("date-reale")
    if cmd == "locatii":
        items = cp.locations()
        print(f"{len(items)} locomotive")
        for it in items[:15]:
            trains = ", ".join(str(t.get("TrainNumber")) for t in it.get("TrainInfo") or [])
            print(f"  {it.get('LocomotiveNumber')}: {it.get('Lat')}, {it.get('Lng')}  tren {trains or '–'}  {it.get('Timestamp')}")
        if items:
            print("Câmpuri disponibile:", ", ".join(sorted(items[0].keys())))
    elif cmd == "comenzi":
        cols, rows, jurnal = cp.comenzi_active()
        print(f"{len(rows)} comenzi active")
        print("Coloane:", " | ".join(cols) or "(nu am găsit tabelul)")
        for j in jurnal:
            print("  ", j)
        d = folder / "comenzi"
        d.mkdir(parents=True, exist_ok=True)
        acum = datetime.now().replace(microsecond=0)
        p = d / f"{acum:%Y-%m-%dT%H-%M-%S}.json"
        p.write_text(json.dumps({"ora": acum.isoformat(), "coloane": cols, "comenzi": rows}, ensure_ascii=False,
                                indent=1), encoding="utf-8")
        print("Salvat local (cu nume – nu se trimite nicăieri):", p)
    elif cmd == "explora":
        print("Raport:", explore(cp, folder / "explorare"))
    elif cmd == "mecanici":
        for p in engineer_tables(cp, folder / "explorare"):
            print("Salvat:", p)
    elif cmd == "inregistreaza":
        _record(cp, folder, int(argv[2]) if len(argv) > 2 else 60)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
