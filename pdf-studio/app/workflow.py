"""Fluxuri de semnare secvențială prin e-mail (SQLite + SMTP + IMAP).

Model: inițiatorul creează un flux cu semnatari (ordine secvențială). Fiecare
semnatar primește PDF-ul pe e-mail (subiect cu tag ``[PDFS-<id>]``), îl semnează
și răspunde cu PDF-ul semnat. Răspunsul este importat (IMAP sau manual),
validat cu ``signing.validate_pdf`` și apoi documentul merge la următorul
semnatar. La final toți participanții primesc documentul complet semnat.

Doar biblioteca standard; ``signing`` este importat leneș.
"""
from __future__ import annotations

import email
import email.policy
import html
import imaplib
import re
import smtplib
import sqlite3
import ssl
import threading
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

__all__ = ["WorkflowStore", "DEFAULT_SETTINGS", "TAG_RE"]

TAG_RE = re.compile(r"\[PDFS-(\d+)\]", re.IGNORECASE)

DEFAULT_SETTINGS: dict = {
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_tls": "starttls",  # "ssl" | "starttls" | "none"
    "from_email": "",
    "from_name": "PDF Studio",
    "imap_host": "",
    "imap_port": 993,
    "imap_user": "",
    "imap_password": "",
    "imap_folder": "INBOX",
    "strict_email_match": False,
}

_INT_SETTINGS = {"smtp_port", "imap_port"}
_BOOL_SETTINGS = {"strict_email_match"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    filename TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    current_step INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id INTEGER NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    email TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    sent_at TEXT,
    signed_at TEXT
);
CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id INTEGER NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    step INTEGER NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sig_count INTEGER,
    data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id INTEGER NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signers_wf ON signers(workflow_id, position);
CREATE INDEX IF NOT EXISTS idx_versions_wf ON versions(workflow_id, id);
CREATE INDEX IF NOT EXISTS idx_events_wf ON events(workflow_id, id);
"""

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tag(wid: int) -> str:
    return f"[PDFS-{wid}]"


def _decode_header(value) -> str:
    if value is None:
        return ""
    try:
        from email.header import decode_header, make_header

        return str(make_header(decode_header(str(value))))
    except Exception:
        return str(value)


def _quote_folder(folder: str) -> str:
    if " " in folder and not folder.startswith('"'):
        return '"' + folder.replace('"', '\\"') + '"'
    return folder


class WorkflowStore:
    """Persistența și logica fluxurilor de semnare. Sigur între fire de execuție:
    fiecare operație deschide o conexiune SQLite nouă, iar tranzițiile de stare
    sunt serializate printr-un lock."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    # ------------------------------------------------------------------ db
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return _ClosingConn(conn)

    def _event(self, c, wid: int, kind: str, message: str) -> None:
        c.execute(
            "INSERT INTO events (workflow_id, ts, kind, message) VALUES (?,?,?,?)",
            (wid, _now(), kind, message),
        )

    def _log(self, wid: int, kind: str, message: str) -> None:
        with self._conn() as c:
            self._event(c, wid, kind, message)

    def _touch(self, c, wid: int, **fields) -> None:
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        c.execute(f"UPDATE workflows SET {cols} WHERE id = ?", (*fields.values(), wid))

    def _row(self, c, wid: int) -> sqlite3.Row:
        row = c.execute("SELECT * FROM workflows WHERE id = ?", (wid,)).fetchone()
        if row is None:
            raise ValueError(f"Fluxul de semnare #{wid} nu există.")
        return row

    def _signers(self, c, wid: int) -> list[dict]:
        rows = c.execute(
            "SELECT * FROM signers WHERE workflow_id = ? ORDER BY position", (wid,)
        ).fetchall()
        return [dict(r) for r in rows]

    def _latest_version(self, c, wid: int) -> sqlite3.Row:
        row = c.execute(
            "SELECT * FROM versions WHERE workflow_id = ? ORDER BY id DESC LIMIT 1", (wid,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Fluxul #{wid} nu are niciun document salvat.")
        return row

    # ------------------------------------------------------------ settings
    def get_settings(self) -> dict:
        out = dict(DEFAULT_SETTINGS)
        with self._conn() as c:
            for r in c.execute("SELECT key, value FROM settings"):
                out[r["key"]] = r["value"]
        for k in _INT_SETTINGS:
            try:
                out[k] = int(out[k]) if out[k] not in (None, "") else DEFAULT_SETTINGS[k]
            except (TypeError, ValueError):
                out[k] = DEFAULT_SETTINGS[k]
        for k in _BOOL_SETTINGS:
            v = out.get(k)
            out[k] = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "da", "on")
        return out

    def save_settings(self, d: dict) -> None:
        if not isinstance(d, dict):
            raise ValueError("Setările trebuie să fie un dicționar.")
        tls = d.get("smtp_tls")
        if tls is not None and tls not in ("ssl", "starttls", "none"):
            raise ValueError("smtp_tls trebuie să fie „ssl”, „starttls” sau „none”.")
        with self._conn() as c:
            for k, v in d.items():
                if k not in DEFAULT_SETTINGS:
                    continue
                if k in _BOOL_SETTINGS:
                    v = "1" if (v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "da", "on")) else "0"
                c.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, "" if v is None else str(v)),
                )

    # ------------------------------------------------------------- create
    def create(self, name, pdf: bytes, filename, signers: list, message: str = "") -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("Numele fluxului este obligatoriu.")
        if not pdf or not bytes(pdf[:1024]).lstrip().startswith(b"%PDF"):
            raise ValueError("Documentul încărcat nu este un PDF valid.")
        if not signers:
            raise ValueError("Adăugați cel puțin un semnatar.")
        clean = []
        for i, s in enumerate(signers, 1):
            em = (s.get("email") or "").strip()
            if not _EMAIL_RE.match(em):
                raise ValueError(f"Adresa de e-mail a semnatarului {i} nu este validă: „{em}”.")
            clean.append((em, (s.get("name") or "").strip() or em))
        filename = (filename or "document.pdf").strip() or "document.pdf"
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        now = _now()
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO workflows (name, filename, message, status, current_step, created_at, updated_at) "
                "VALUES (?,?,?,'draft',0,?,?)",
                (name, filename, message or "", now, now),
            )
            wid = cur.lastrowid
            for pos, (em, nm) in enumerate(clean):
                c.execute(
                    "INSERT INTO signers (workflow_id, position, email, name, status) VALUES (?,?,?,?,'pending')",
                    (wid, pos, em, nm),
                )
            c.execute(
                "INSERT INTO versions (workflow_id, step, source, created_at, sig_count, data) VALUES (?,?,?,?,?,?)",
                (wid, 0, "original", now, None, sqlite3.Binary(bytes(pdf))),
            )
            self._event(c, wid, "created", f"Flux creat cu {len(clean)} semnatar(i).")
        return wid

    # --------------------------------------------------------------- read
    def list(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM workflows ORDER BY id DESC").fetchall()
            out = []
            for r in rows:
                d = dict(r)
                signers = self._signers(c, r["id"])
                d["signer_count"] = len(signers)
                d["signed_count"] = sum(1 for s in signers if s["status"] == "signed")
                cur = signers[r["current_step"]] if r["current_step"] < len(signers) else None
                d["current_signer"] = cur
                out.append(d)
            return out

    def get(self, id) -> dict:
        wid = int(id)
        with self._conn() as c:
            d = dict(self._row(c, wid))
            d["tag"] = _tag(wid)
            d["signers"] = self._signers(c, wid)
            d["events"] = [
                dict(r)
                for r in c.execute(
                    "SELECT id, ts, kind, message FROM events WHERE workflow_id = ? ORDER BY id", (wid,)
                )
            ]
            d["versions"] = [
                dict(r)
                for r in c.execute(
                    "SELECT id, step, source, created_at, sig_count, length(data) AS size "
                    "FROM versions WHERE workflow_id = ? ORDER BY id",
                    (wid,),
                )
            ]
            return d

    def get_document(self, id) -> tuple[str, bytes]:
        wid = int(id)
        with self._conn() as c:
            row = self._row(c, wid)
            v = self._latest_version(c, wid)
            return row["filename"], bytes(v["data"])

    # -------------------------------------------------------------- email
    def _send(self, to: list[str], subject: str, text: str, html_body: str,
              attachment: tuple[str, bytes] | None = None, settings: dict | None = None) -> None:
        s = settings or self.get_settings()
        if not s.get("smtp_host"):
            raise ValueError("Serverul SMTP nu este configurat (Setări → E-mail).")
        from_email = s.get("from_email") or s.get("smtp_user")
        if not from_email:
            raise ValueError("Adresa expeditorului (from_email) nu este configurată.")
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr((s.get("from_name") or "", from_email))
        msg["To"] = ", ".join(to)
        msg["Reply-To"] = from_email
        msg.set_content(text)
        msg.add_alternative(html_body, subtype="html")
        if attachment:
            fname, data = attachment
            msg.add_attachment(data, maintype="application", subtype="pdf", filename=fname)
        with self._smtp(s) as smtp:
            smtp.send_message(msg)

    def _smtp(self, s: dict):
        host, port, mode = s["smtp_host"], int(s.get("smtp_port") or 0), s.get("smtp_tls") or "starttls"
        try:
            if mode == "ssl":
                smtp = smtplib.SMTP_SSL(host, port or 465, timeout=30, context=ssl.create_default_context())
            else:
                smtp = smtplib.SMTP(host, port or 587, timeout=30)
                if mode == "starttls":
                    smtp.ehlo()
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
            if s.get("smtp_user"):
                smtp.login(s["smtp_user"], s.get("smtp_password") or "")
        except (OSError, smtplib.SMTPException) as e:
            raise ValueError(f"Conectare SMTP eșuată: {e}") from e
        return smtp

    @staticmethod
    def _html(title: str, paragraphs: list[str], items: list[str] | None = None, note: str = "") -> str:
        ps = "".join(f'<p style="margin:0 0 12px">{p}</p>' for p in paragraphs)
        lst = ""
        if items:
            lst = '<ol style="margin:0 0 12px;padding-left:20px">' + "".join(
                f'<li style="margin-bottom:6px">{i}</li>' for i in items) + "</ol>"
        nt = f'<p style="margin:16px 0 0;color:#666;font-size:12px">{note}</p>' if note else ""
        return (
            '<!doctype html><html><body style="margin:0;padding:24px;background:#f4f5f7;'
            'font-family:Segoe UI,Arial,sans-serif;color:#222;font-size:14px;line-height:1.5">'
            '<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:8px;'
            'border:1px solid #e2e4e8;padding:24px">'
            f'<h2 style="margin:0 0 16px;font-size:18px;color:#1a4fa0">{title}</h2>'
            f"{ps}{lst}{nt}</div></body></html>"
        )

    def _request_email(self, wf: dict, signer: dict, pdf: bytes, reminder: bool = False,
                       settings: dict | None = None) -> None:
        wid = wf["id"]
        prefix = "Reamintire: " if reminder else ""
        subject = f"{_tag(wid)} {prefix}Solicitare semnare: {wf['name']}"
        steps = [
            "Deschideți documentul PDF atașat.",
            "Semnați-l cu certificatul calificat (de ex. în PDF Studio sau Adobe Acrobat Reader).",
            "Răspundeți la acest e-mail atașând PDF-ul semnat.",
            f"Păstrați subiectul mesajului (trebuie să conțină {_tag(wid)}).",
        ]
        msg = (wf.get("message") or "").strip()
        greet = f"Bună ziua, {signer['name']},"
        intro = (f"Vă rugăm să semnați documentul „{wf['name']}” "
                 f"(fișier: {wf['filename']}).")
        if reminder:
            intro = "Vă reamintim că documentul " + f"„{wf['name']}” așteaptă semnătura dumneavoastră."
        text = [greet, "", intro, ""]
        if msg:
            text += ["Mesaj de la inițiator:", msg, ""]
        text += ["Pași:"] + [f"  {i}. {s}" for i, s in enumerate(steps, 1)]
        text += ["", "Mulțumim!", "", "— Trimis automat de PDF Studio"]
        paras = [html.escape(greet), html.escape(intro)]
        if msg:
            paras.append("<b>Mesaj de la inițiator:</b><br>" + html.escape(msg).replace("\n", "<br>"))
        paras.append("<b>Pași:</b>")
        body_html = self._html(
            ("Reamintire: " if reminder else "") + "Solicitare de semnare",
            paras, [html.escape(s) for s in steps],
            "Mesaj trimis automat de PDF Studio. Nu modificați subiectul la răspuns.",
        )
        self._send([signer["email"]], subject, "\n".join(text), body_html,
                   (wf["filename"], pdf), settings)

    def _completed_email(self, wf: dict, signers: list[dict], pdf: bytes, settings: dict) -> list[str]:
        recipients = []
        for s in signers:
            if s["email"].lower() not in {r.lower() for r in recipients}:
                recipients.append(s["email"])
        init = settings.get("from_email") or settings.get("smtp_user")
        if init and init.lower() not in {r.lower() for r in recipients}:
            recipients.append(init)
        subject = f"{_tag(wf['id'])} Document semnat complet: {wf['name']}"
        names = [f"{s['name']} <{s['email']}>" for s in signers]
        intro = f"Documentul „{wf['name']}” a fost semnat de toți semnatarii."
        text = "\n".join(["Bună ziua,", "", intro, "", "Semnatari:"] + [f"  - {n}" for n in names]
                         + ["", "Documentul final este atașat.", "", "— Trimis automat de PDF Studio"])
        body_html = self._html(
            "Document semnat complet",
            ["Bună ziua,", html.escape(intro), "<b>Semnatari:</b>"],
            [html.escape(n) for n in names],
            "Documentul final, cu toate semnăturile, este atașat acestui mesaj.",
        )
        self._send(recipients, subject, text, body_html, (wf["filename"], pdf), settings)
        return recipients

    # ------------------------------------------------------------ actions
    def start(self, id) -> dict:
        wid = int(id)
        with self._lock:
            with self._conn() as c:
                wf = dict(self._row(c, wid))
                if wf["status"] != "draft":
                    raise ValueError("Fluxul a fost deja pornit.")
                signers = self._signers(c, wid)
                pdf = bytes(self._latest_version(c, wid)["data"])
            first = signers[0]
            try:
                self._request_email(wf, first, pdf)
            except ValueError as e:
                self._log(wid, "error", f"Trimiterea către {first['email']} a eșuat: {e}")
                raise
            with self._conn() as c:
                self._touch(c, wid, status="in_progress", current_step=0)
                c.execute("UPDATE signers SET status='sent', sent_at=? WHERE id=?", (_now(), first["id"]))
                self._event(c, wid, "sent", f"Document trimis spre semnare către {first['name']} <{first['email']}>.")
        return self.get(wid)

    def _sig_count(self, c, version_row) -> int:
        if version_row["sig_count"] is not None:
            return int(version_row["sig_count"])
        from . import signing

        try:
            n = len(signing.validate_pdf(bytes(version_row["data"])))
        except Exception:
            n = 0
        c.execute("UPDATE versions SET sig_count=? WHERE id=?", (n, version_row["id"]))
        return n

    def submit_signed(self, id, pdf: bytes, source: str = "manual") -> dict:
        wid = int(id)
        if not pdf or not bytes(pdf[:1024]).lstrip().startswith(b"%PDF"):
            raise ValueError("Fișierul primit nu este un PDF valid.")
        from . import signing

        with self._lock:
            settings = self.get_settings()
            with self._conn() as c:
                wf = dict(self._row(c, wid))
                if wf["status"] != "in_progress":
                    raise ValueError(
                        f"Fluxul #{wid} nu este în desfășurare (stare: {wf['status']}).")
                signers = self._signers(c, wid)
                step = wf["current_step"]
                if step >= len(signers):
                    raise ValueError("Toți semnatarii au semnat deja.")
                expected = signers[step]
                prev_count = self._sig_count(c, self._latest_version(c, wid))

            def reject(msg: str):
                self._log(wid, "rejected", f"Document respins ({source}): {msg}")
                raise ValueError(msg)

            try:
                sigs = signing.validate_pdf(bytes(pdf))
            except ValueError as e:
                reject(f"Validarea semnăturilor a eșuat: {e}")
            except Exception as e:  # noqa: BLE001
                reject(f"Validarea semnăturilor a eșuat: {e}")

            if len(sigs) <= prev_count:
                reject(
                    f"Documentul nu conține o semnătură nouă (semnături găsite: {len(sigs)}, "
                    f"anterior: {prev_count}). Așteptat: semnătura lui {expected['name']} <{expected['email']}>.")
            broken = [s for s in sigs if not s.get("intact")]
            if broken:
                old = [s for s in broken if sigs.index(s) < prev_count]
                which = old or broken
                names = ", ".join(f"{s.get('signer_name') or s.get('field') or '?'}" for s in which)
                if old:
                    reject("O semnătură anterioară nu mai este intactă (documentul a fost modificat "
                           f"după semnare): {names}.")
                reject(f"Semnătura nouă nu este intactă: {names}.")

            newest = sigs[-1]
            warnings: list[str] = []
            for s in sigs:
                if s.get("intact") and not s.get("valid"):
                    label = s.get("signer_name") or s.get("field") or "?"
                    w = f"Semnătura „{label}” nu a putut fi validată complet."
                    if s.get("errors"):
                        w += " " + "; ".join(str(x) for x in s["errors"])
                    warnings.append(w)
            sig_email = (newest.get("signer_email") or "").strip()
            if sig_email.lower() != expected["email"].strip().lower():
                mm = (f"Adresa din certificatul semnăturii noi („{sig_email or 'necunoscută'}”, "
                      f"{newest.get('signer_name') or '?'}) diferă de adresa semnatarului așteptat "
                      f"({expected['email']}).")
                if settings.get("strict_email_match"):
                    reject(mm)
                warnings.append(mm)

            now = _now()
            is_last = step + 1 >= len(signers)
            with self._conn() as c:
                c.execute(
                    "INSERT INTO versions (workflow_id, step, source, created_at, sig_count, data) VALUES (?,?,?,?,?,?)",
                    (wid, step + 1, source, now, len(sigs), sqlite3.Binary(bytes(pdf))),
                )
                c.execute("UPDATE signers SET status='signed', signed_at=? WHERE id=?", (now, expected["id"]))
                self._event(c, wid, "signed",
                            f"Semnat de {expected['name']} <{expected['email']}> (sursa: {source}; "
                            f"semnătură: {newest.get('signer_name') or '?'}).")
                for w in warnings:
                    self._event(c, wid, "warning", w)
                if is_last:
                    self._touch(c, wid, status="completed", current_step=len(signers))
                    self._event(c, wid, "completed", "Toți semnatarii au semnat. Flux finalizat.")
                else:
                    self._touch(c, wid, current_step=step + 1)

            next_signer = None
            notified: list[str] = []
            wf_now = dict(wf, current_step=step + 1)
            if is_last:
                try:
                    notified = self._completed_email(wf_now, signers, bytes(pdf), settings)
                    self._log(wid, "sent", "Documentul final a fost trimis către: " + ", ".join(notified) + ".")
                except ValueError as e:
                    w = f"Trimiterea documentului final a eșuat: {e}"
                    warnings.append(w)
                    self._log(wid, "error", w)
            else:
                next_signer = signers[step + 1]
                try:
                    self._request_email(wf_now, next_signer, bytes(pdf), settings=settings)
                    with self._conn() as c:
                        c.execute("UPDATE signers SET status='sent', sent_at=? WHERE id=?", (_now(), next_signer["id"]))
                        self._event(c, wid, "sent", f"Document trimis spre semnare către "
                                                    f"{next_signer['name']} <{next_signer['email']}>.")
                except ValueError as e:
                    w = (f"Trimiterea către {next_signer['email']} a eșuat: {e}. "
                         "Folosiți „Reamintire” după corectarea setărilor.")
                    warnings.append(w)
                    self._log(wid, "error", w)

        return {
            "ok": True,
            "workflow_id": wid,
            "step": step,
            "source": source,
            "signer": {"email": expected["email"], "name": expected["name"]},
            "signatures": sigs,
            "signature_count": len(sigs),
            "warnings": warnings,
            "completed": is_last,
            "status": "completed" if is_last else "in_progress",
            "next_signer": ({"email": next_signer["email"], "name": next_signer["name"]} if next_signer else None),
            "notified": notified,
            "message": ("Document semnat complet; toți participanții au fost notificați." if is_last
                        else f"Semnătură acceptată. Documentul a fost trimis către {next_signer['name']}."),
        }

    def sign_current_step_locally(self, id, signed_pdf: bytes) -> dict:
        return self.submit_signed(id, signed_pdf, source="local")

    def remind(self, id) -> dict:
        wid = int(id)
        with self._conn() as c:
            wf = dict(self._row(c, wid))
            if wf["status"] != "in_progress":
                raise ValueError("Reamintirea se poate trimite doar pentru fluxuri în desfășurare.")
            signer = self._signers(c, wid)[wf["current_step"]]
            pdf = bytes(self._latest_version(c, wid)["data"])
        try:
            self._request_email(wf, signer, pdf, reminder=True)
        except ValueError as e:
            self._log(wid, "error", f"Reamintirea către {signer['email']} a eșuat: {e}")
            raise
        with self._conn() as c:
            c.execute("UPDATE signers SET status='sent', sent_at=? WHERE id=?", (_now(), signer["id"]))
            self._event(c, wid, "reminder", f"Reamintire trimisă către {signer['name']} <{signer['email']}>.")
        return {"ok": True, "message": f"Reamintire trimisă către {signer['email']}."}

    def cancel(self, id) -> dict:
        wid = int(id)
        with self._lock, self._conn() as c:
            wf = self._row(c, wid)
            if wf["status"] in ("completed", "cancelled"):
                raise ValueError("Fluxul este deja finalizat sau anulat.")
            self._touch(c, wid, status="cancelled")
            self._event(c, wid, "cancelled", "Flux anulat de inițiator.")
        return {"ok": True, "message": "Fluxul a fost anulat."}

    # --------------------------------------------------------------- IMAP
    def _imap(self, s: dict):
        if not s.get("imap_host"):
            raise ValueError("Serverul IMAP nu este configurat (Setări → E-mail).")
        try:
            m = imaplib.IMAP4_SSL(s["imap_host"], int(s.get("imap_port") or 993),
                                  ssl_context=ssl.create_default_context())
            m.login(s.get("imap_user") or "", s.get("imap_password") or "")
        except (OSError, imaplib.IMAP4.error) as e:
            raise ValueError(f"Conectare IMAP eșuată: {e}") from e
        return m

    @staticmethod
    def _pdf_attachments(msg) -> list[tuple[str, bytes]]:
        out = []
        for part in msg.walk():
            if part.is_multipart():
                continue
            fname = _decode_header(part.get_filename()) or ""
            ctype = part.get_content_type()
            if ctype == "application/pdf" or fname.lower().endswith(".pdf"):
                data = part.get_payload(decode=True)
                if data:
                    out.append((fname or "document.pdf", data))
        return out

    def check_inbox(self) -> list[dict]:
        s = self.get_settings()
        m = self._imap(s)
        results: list[dict] = []
        try:
            folder = s.get("imap_folder") or "INBOX"
            typ, _ = m.select(_quote_folder(folder))
            if typ != "OK":
                raise ValueError(f"Dosarul IMAP „{folder}” nu poate fi deschis.")
            typ, data = m.uid("SEARCH", None, "UNSEEN")
            if typ != "OK":
                raise ValueError("Căutarea mesajelor necitite a eșuat.")
            uids = (data[0] or b"").split() if data else []
            for uid in uids:
                uid_s = uid.decode() if isinstance(uid, bytes) else str(uid)
                res: dict = {"uid": uid_s, "ok": False}
                try:
                    typ, hdr = m.uid("FETCH", uid_s, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])")
                    raw_hdr = next((p[1] for p in (hdr or []) if isinstance(p, tuple)), b"")
                    h = email.message_from_bytes(raw_hdr, policy=email.policy.default)
                    subject = _decode_header(h.get("Subject"))
                    match = TAG_RE.search(subject)
                    if not match:
                        continue  # nu ne aparține; rămâne necitit
                    res.update(subject=subject, sender=parseaddr(str(h.get("From") or ""))[1],
                               workflow_id=int(match.group(1)))
                    typ, body = m.uid("FETCH", uid_s, "(BODY.PEEK[])")
                    raw = next((p[1] for p in (body or []) if isinstance(p, tuple)), None)
                    if not raw:
                        raise ValueError("Mesajul nu a putut fi descărcat.")
                    msg = email.message_from_bytes(raw, policy=email.policy.default)
                    pdfs = self._pdf_attachments(msg)
                    if not pdfs:
                        raise ValueError("Mesajul nu conține niciun atașament PDF.")
                    errors = []
                    for fname, data in pdfs:
                        try:
                            res["report"] = self.submit_signed(res["workflow_id"], data, source="email")
                            res["filename"] = fname
                            res["ok"] = True
                            break
                        except ValueError as e:
                            errors.append(f"{fname}: {e}")
                    if not res["ok"]:
                        res["error"] = " | ".join(errors)
                except Exception as e:  # noqa: BLE001 – erorile per mesaj nu opresc procesarea
                    res["error"] = str(e) or e.__class__.__name__
                finally:
                    if "workflow_id" in res:
                        try:
                            m.uid("STORE", uid_s, "+FLAGS", "(\\Seen)")
                        except Exception:  # noqa: BLE001
                            pass
                if "workflow_id" in res:
                    results.append(res)
        finally:
            try:
                m.logout()
            except Exception:  # noqa: BLE001
                pass
        return results

    # -------------------------------------------------------------- tests
    def test_smtp(self) -> dict:
        s = self.get_settings()
        try:
            if not s.get("smtp_host"):
                raise ValueError("Serverul SMTP nu este configurat.")
            smtp = self._smtp(s)
            try:
                smtp.noop()
            finally:
                try:
                    smtp.quit()
                except Exception:  # noqa: BLE001
                    pass
            return {"ok": True, "message": f"Conexiunea SMTP la {s['smtp_host']} funcționează."}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": str(e)}

    def test_imap(self) -> dict:
        s = self.get_settings()
        try:
            m = self._imap(s)
            try:
                folder = s.get("imap_folder") or "INBOX"
                typ, _ = m.select(_quote_folder(folder), readonly=True)
                if typ != "OK":
                    raise ValueError(f"Dosarul „{folder}” nu poate fi deschis.")
            finally:
                try:
                    m.logout()
                except Exception:  # noqa: BLE001
                    pass
            return {"ok": True, "message": f"Conexiunea IMAP la {s['imap_host']} funcționează."}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": str(e)}


class _ClosingConn:
    """Context manager: commit/rollback și închide conexiunea la ieșire."""

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def __getattr__(self, name):
        return getattr(self._c, name)

    def __enter__(self):
        return self._c

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._c.commit()
            else:
                self._c.rollback()
        finally:
            self._c.close()
        return False
