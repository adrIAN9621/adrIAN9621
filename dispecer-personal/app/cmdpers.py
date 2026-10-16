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
POST_PERMIS = re.compile(r"/(Get|Search|Cauta|Find|List|Load|Read)[A-Za-z]*$", re.I)
INTERZIS = re.compile(r"(save|delete|sterge|update|create|add|edit|insert|set|remove|approve|aproba|"
                      r"trimite|send|import|upload|logoff|logout|deconect|reset|change|modif|anul|cancel)", re.I)
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

    def _raw(self, method: str, url: str, data: Optional[dict] = None, ajax: bool = False,
             referer: Optional[str] = None) -> tuple[str, str, str]:
        """→ (url final după redirect, content-type, text)"""
        path = urllib.parse.urlparse(url).path
        if method != "GET":
            if INTERZIS.search(path) or not POST_PERMIS.search(path.rstrip("/")) and not path.endswith("/Account/Login"):
                raise Refuzat(f"POST blocat (doar citire): {path}")
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
                    continue
                return srv
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                errors.append(f"{srv}: {getattr(e, 'reason', e)}")
        self.server = None
        raise LoginEsuat("Logare CmdPers eșuată – " + "; ".join(errors))

    def _ensure(self) -> None:
        if self.server is None:
            self.login()

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
                self.login()
        raise AssertionError("unreachable")

    def get(self, path: str) -> str:
        return self.request("GET", path)[2]

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
def explore(cp: CmdPers, out: Path, max_pages: int = 80) -> Path:
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
        if key in seen or INTERZIS.search(path.split("?")[0]):
            continue
        seen.add(key)
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
            if n and n.split("?")[0].rstrip("/").lower() not in seen and not INTERZIS.search(n.split("?")[0]):
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
        time.sleep(interval)


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "test"
    if cmd not in ("test", "locatii", "explora", "mecanici", "inregistreaza"):
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
