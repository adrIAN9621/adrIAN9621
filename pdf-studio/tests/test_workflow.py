import email
import email.policy
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402
from app import workflow  # noqa: E402

# --------------------------------------------------------------------------- fakes
# PDF fals: "%PDF-1.7\n" urmat de linii "SIG|email|intact(1/0)" – câte una pe semnătură.


def make_pdf(*sigs):
    lines = [b"%PDF-1.7"]
    for em, intact in sigs:
        lines.append(f"SIG|{em}|{1 if intact else 0}".encode())
    return b"\n".join(lines) + b"\n%%EOF"


def fake_validate_pdf(pdf, extra_trust_roots=None):
    out = []
    for i, line in enumerate(pdf.splitlines()):
        if line.startswith(b"SIG|"):
            _, em, intact = line.decode().split("|")
            out.append({
                "field": f"Sig{i}", "signer_name": em.split("@")[0].title(), "signer_email": em,
                "signing_time": None, "intact": intact == "1", "valid": intact == "1", "trusted": True,
                "coverage": "ENTIRE_REVISION", "modification_level": "NONE", "timestamp": None,
                "cert_subject": em, "cert_issuer": "Test CA", "cert_not_after": None,
                "summary": "ok", "errors": [],
            })
    return out


class FakeSMTP:
    sent = []

    def __init__(self, host, port=0, timeout=None, context=None):
        self.host, self.port = host, port

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, user, pwd):
        pass

    def noop(self):
        return (250, b"OK")

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)

    def quit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    FakeSMTP.sent = []
    fake_signing = types.ModuleType("app.signing")
    fake_signing.validate_pdf = fake_validate_pdf
    monkeypatch.setitem(sys.modules, "app.signing", fake_signing)
    monkeypatch.setattr(app, "signing", fake_signing, raising=False)
    monkeypatch.setattr(workflow.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(workflow.smtplib, "SMTP_SSL", FakeSMTP)


@pytest.fixture
def store(tmp_path):
    st = workflow.WorkflowStore(str(tmp_path / "wf.db"))
    st.save_settings({
        "smtp_host": "smtp.test", "smtp_port": 587, "smtp_tls": "starttls",
        "smtp_user": "init@firma.ro", "smtp_password": "x",
        "from_email": "init@firma.ro", "from_name": "Inițiator",
        "imap_host": "imap.test", "imap_user": "init@firma.ro", "imap_password": "x",
    })
    return st


SIGNERS = [{"email": "ana@firma.ro", "name": "Ana Pop"}, {"email": "Bogdan@Firma.ro", "name": "Bogdan Ion"}]


def new_flow(store):
    wid = store.create("Contract 12", make_pdf(), "contract.pdf", SIGNERS, "Vă rog semnați azi.")
    store.start(wid)
    return wid


def attachments(msg):
    return [p for p in msg.iter_attachments() if p.get_content_type() == "application/pdf"]


# --------------------------------------------------------------------------- tests


def test_settings_roundtrip(store):
    s = store.get_settings()
    assert s["smtp_port"] == 587 and s["strict_email_match"] is False
    store.save_settings({"strict_email_match": True})
    assert store.get_settings()["strict_email_match"] is True


def test_full_two_signer_flow(store):
    wid = new_flow(store)
    wf = store.get(wid)
    assert wf["status"] == "in_progress"
    assert [s["status"] for s in wf["signers"]] == ["sent", "pending"]
    assert len(FakeSMTP.sent) == 1
    m = FakeSMTP.sent[0]
    assert m["Subject"] == f"[PDFS-{wid}] Solicitare semnare: Contract 12"
    assert m["To"] == "ana@firma.ro"
    assert len(attachments(m)) == 1
    text = m.get_body(("plain",)).get_content()
    assert "Vă rog semnați azi." in text and "Răspundeți" in text
    assert m.get_body(("html",)) is not None

    r1 = store.submit_signed(wid, make_pdf(("ana@firma.ro", True)))
    assert r1["ok"] and not r1["completed"] and r1["warnings"] == []
    assert r1["next_signer"]["email"] == "Bogdan@Firma.ro"
    assert FakeSMTP.sent[-1]["To"] == "Bogdan@Firma.ro"
    wf = store.get(wid)
    assert wf["current_step"] == 1
    assert [s["status"] for s in wf["signers"]] == ["signed", "sent"]

    final = make_pdf(("ana@firma.ro", True), ("bogdan@firma.ro", True))  # e-mail case-insensitive
    r2 = store.sign_current_step_locally(wid, final)
    assert r2["completed"] and r2["warnings"] == []
    wf = store.get(wid)
    assert wf["status"] == "completed"
    assert all(s["status"] == "signed" for s in wf["signers"])
    assert [v["source"] for v in wf["versions"]] == ["original", "manual", "local"]
    assert store.get_document(wid) == ("contract.pdf", final)

    last = FakeSMTP.sent[-1]
    assert len(FakeSMTP.sent) == 3
    to = {a.strip().lower() for a in last["To"].split(",")}
    assert to == {"ana@firma.ro", "bogdan@firma.ro", "init@firma.ro"}
    assert bytes(attachments(last)[0].get_content()) == final

    with pytest.raises(ValueError):
        store.submit_signed(wid, final)


def test_no_new_signature_rejected(store):
    wid = new_flow(store)
    with pytest.raises(ValueError, match="semnătură nouă"):
        store.submit_signed(wid, make_pdf())
    assert store.get(wid)["current_step"] == 0


def test_email_mismatch_warning(store):
    wid = new_flow(store)
    r = store.submit_signed(wid, make_pdf(("altcineva@x.ro", True)))
    assert r["ok"] and len(r["warnings"]) == 1 and "diferă" in r["warnings"][0]
    ev = store.get(wid)["events"]
    assert any(e["kind"] == "warning" and "altcineva@x.ro" in e["message"] for e in ev)


def test_email_mismatch_strict_rejects(store):
    store.save_settings({"strict_email_match": True})
    wid = new_flow(store)
    with pytest.raises(ValueError, match="diferă"):
        store.submit_signed(wid, make_pdf(("altcineva@x.ro", True)))
    wf = store.get(wid)
    assert wf["current_step"] == 0 and wf["signers"][0]["status"] == "sent"


def test_broken_previous_signature_rejected(store):
    wid = new_flow(store)
    store.submit_signed(wid, make_pdf(("ana@firma.ro", True)))
    with pytest.raises(ValueError, match="anterioar"):
        store.submit_signed(wid, make_pdf(("ana@firma.ro", False), ("bogdan@firma.ro", True)))
    wf = store.get(wid)
    assert wf["current_step"] == 1 and wf["status"] == "in_progress"
    assert any(e["kind"] == "rejected" for e in wf["events"])


def test_remind_and_cancel(store):
    wid = new_flow(store)
    assert store.remind(wid)["ok"]
    assert "Reamintire" in FakeSMTP.sent[-1]["Subject"]
    store.cancel(wid)
    assert store.get(wid)["status"] == "cancelled"
    with pytest.raises(ValueError):
        store.submit_signed(wid, make_pdf(("ana@firma.ro", True)))


def test_test_smtp(store):
    assert store.test_smtp()["ok"] is True


# ------------------------------------------------------------------ IMAP


def build_reply(subject, pdf=None):
    msg = email.message.EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "Ana <ana@firma.ro>"
    msg["To"] = "init@firma.ro"
    msg.set_content("Atașat documentul semnat.")
    if pdf is not None:
        msg.add_attachment(pdf, maintype="application", subtype="pdf", filename="semnat.pdf")
    return msg.as_bytes()


class FakeIMAP:
    messages = {}
    seen = set()

    def __init__(self, host, port=993, ssl_context=None):
        pass

    def login(self, u, p):
        return "OK", [b""]

    def select(self, folder, readonly=False):
        return "OK", [str(len(self.messages)).encode()]

    def logout(self):
        return "BYE", [b""]

    def uid(self, cmd, *args):
        cmd = cmd.upper()
        if cmd == "SEARCH":
            return "OK", [b" ".join(k.encode() for k in self.messages if k not in self.seen)]
        if cmd == "FETCH":
            uid, what = args
            raw = self.messages[uid]
            if "HEADER" in what:
                raw = raw.split(b"\n\n", 1)[0] + b"\n\n"
            return "OK", [(f"{uid} (BODY[] {{{len(raw)}}}".encode(), raw), b")"]
        if cmd == "STORE":
            self.seen.add(args[0])
            return "OK", [b""]
        raise AssertionError(cmd)


def test_check_inbox(store, monkeypatch):
    wid = new_flow(store)
    FakeIMAP.seen = set()
    FakeIMAP.messages = {
        "1": build_reply("Salut, fără tag", make_pdf(("ana@firma.ro", True))),
        "2": build_reply(f"Re: [PDFS-{wid}] Solicitare semnare: Contract 12"),  # fără atașament
        "3": build_reply(f"Re: [PDFS-{wid}] Solicitare semnare: Contract 12", make_pdf(("ana@firma.ro", True))),
        "4": build_reply("Re: [PDFS-9999] ceva", make_pdf(("x@y.ro", True))),
    }
    monkeypatch.setattr(workflow.imaplib, "IMAP4_SSL", FakeIMAP)

    res = store.check_inbox()
    by_uid = {r["uid"]: r for r in res}
    assert set(by_uid) == {"2", "3", "4"}
    assert not by_uid["2"]["ok"] and "atașament" in by_uid["2"]["error"]
    assert by_uid["3"]["ok"] and by_uid["3"]["report"]["source"] == "email"
    assert not by_uid["4"]["ok"] and "nu există" in by_uid["4"]["error"]
    assert FakeIMAP.seen == {"2", "3", "4"}  # mesajul fără tag rămâne necitit

    wf = store.get(wid)
    assert wf["current_step"] == 1 and wf["versions"][-1]["source"] == "email"
    assert FakeSMTP.sent[-1]["To"] == "Bogdan@Firma.ro"

    assert store.check_inbox() == []
    assert store.test_imap()["ok"] is True
