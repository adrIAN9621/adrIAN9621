import os
import shutil
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import signing  # noqa: E402


def make_pdf(pages=2) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Contract de test - pagina {i + 1}", fontsize=14)
    data = doc.tobytes()
    doc.close()
    return data


def _pfx_cert_der(pfx: bytes, password: str) -> bytes:
    from cryptography.hazmat.primitives.serialization import Encoding, pkcs12

    _key, cert, _ = pkcs12.load_key_and_certificates(pfx, password.encode())
    return cert.public_bytes(Encoding.DER)


@pytest.fixture(scope="module")
def pfx_pair():
    a = signing.make_test_pfx("Ion Popescu", "ion@example.ro", "parola1")
    b = signing.make_test_pfx("Maria Ionescu", "maria@example.ro", "parola2")
    return a, b


@pytest.fixture(scope="module")
def double_signed(pfx_pair):
    a, b = pfx_pair
    pdf = make_pdf()
    s1 = signing.sign_pdf(
        pdf, method="pkcs12", params={"pfx": a, "password": "parola1"},
        reason="Aprobare", location="București",
    )
    s2 = signing.sign_pdf(
        s1, method="pkcs12", params={"pfx": b, "password": "parola2"},
        reason="Am luat la cunoștință", location="Cluj-Napoca",
        visible={"page": 1, "x": 50, "y": 50, "w": 220, "h": 80},
    )
    return pdf, s1, s2


def test_incremental(double_signed):
    pdf, s1, s2 = double_signed
    assert s1.startswith(pdf)
    assert s2.startswith(s1)


def test_two_signatures_valid(double_signed, pfx_pair):
    _, _, s2 = double_signed
    res = signing.validate_pdf(s2)
    assert [r["field"] for r in res] == ["Semnatura1", "Semnatura2"]
    expected_keys = {
        "field", "signer_name", "signer_email", "signing_time", "intact", "valid",
        "trusted", "coverage", "modification_level", "timestamp", "cert_subject",
        "cert_issuer", "cert_not_after", "summary", "errors",
    }
    for r in res:
        assert set(r) == expected_keys
        assert r["intact"] is True and r["valid"] is True, r
        assert r["trusted"] is False  # auto-semnat
        assert "neîncrezut" in r["summary"]
        assert r["signing_time"]
    assert res[0]["signer_name"] == "Ion Popescu"
    assert res[0]["signer_email"] == "ion@example.ro"
    assert res[1]["signer_name"] == "Maria Ionescu"
    assert res[1]["coverage"] == "ENTIRE_FILE"
    assert res[1]["modification_level"] == "NONE"
    assert res[1]["summary"].startswith("Semnătură validă, document nemodificat")
    assert res[0]["coverage"] == "ENTIRE_REVISION"
    assert res[0]["modification_level"] in ("FORM_FILLING", "NONE")

    # cu rădăcini de încredere suplimentare (DER și PEM) -> trusted
    import base64

    a, b = pfx_pair
    der_a = _pfx_cert_der(a, "parola1")
    der_b = _pfx_cert_der(b, "parola2")
    pem_b = (
        b"-----BEGIN CERTIFICATE-----\n"
        + base64.encodebytes(der_b)
        + b"-----END CERTIFICATE-----\n"
    )
    res = signing.validate_pdf(s2, extra_trust_roots=[der_a, pem_b])
    assert all(r["trusted"] for r in res), res
    assert "Certificat de încredere" in res[1]["summary"]


def test_visible_widget(double_signed):
    _, _, s2 = double_signed
    doc = fitz.open(stream=s2, filetype="pdf")
    widgets = list(doc[1].widgets())
    assert any(w.field_name == "Semnatura2" for w in widgets)
    w = [w for w in widgets if w.field_name == "Semnatura2"][0]
    assert abs(w.rect.width - 220) < 1 and abs(w.rect.height - 80) < 1
    doc.close()


def test_non_incremental_modification_detected(double_signed):
    _, _, s2 = double_signed
    doc = fitz.open(stream=s2, filetype="pdf")
    doc[0].insert_text((72, 200), "TEXT ADAUGAT", fontsize=20)
    modified = doc.tobytes(garbage=3)  # rescriere completă
    doc.close()
    res = signing.validate_pdf(modified)
    assert res, "semnăturile ar trebui încă găsite"
    for r in res:
        bad = (not r["intact"]) or r["modification_level"] == "OTHER" or r["errors"]
        assert bad, r
        assert "modificat" in r["summary"].lower() or not r["valid"], r


def test_incremental_tamper_detected(double_signed, tmp_path):
    """Modificare de conținut adăugată incremental -> modification_level OTHER."""
    _, _, s2 = double_signed
    f = tmp_path / "t.pdf"
    f.write_bytes(s2)
    doc = fitz.open(str(f))
    doc[0].insert_text((72, 300), "FRAUDA", fontsize=20)
    doc.save(str(f), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()
    out = f.read_bytes()
    assert out.startswith(s2)
    res = signing.validate_pdf(out)
    for r in res:
        assert r["intact"] is True
        assert r["modification_level"] == "OTHER", r
        assert "modificat" in r["summary"]


def test_invalid_password(pfx_pair):
    a, _ = pfx_pair
    with pytest.raises(ValueError):
        signing.sign_pdf(make_pdf(1), method="pkcs12", params={"pfx": a, "password": "gresit"})


def test_unsigned_pdf_and_garbage():
    assert signing.validate_pdf(make_pdf(1)) == []
    with pytest.raises(ValueError):
        signing.validate_pdf(b"nu e pdf")


def test_explicit_field_name_and_running_loop(pfx_pair):
    """sign_pdf apelat dintr-un context cu event loop activ."""
    import asyncio

    a, _ = pfx_pair

    async def inner():
        return signing.sign_pdf(
            make_pdf(1), method="pkcs12", params={"pfx": a, "password": "parola1"},
            field_name="SemnaturaDirector",
            visible={"page": 0, "x": 300, "y": 600, "w": 200, "h": 70},
        )

    out = asyncio.run(inner())
    res = signing.validate_pdf(out)
    assert res[0]["field"] == "SemnaturaDirector" and res[0]["intact"] and res[0]["valid"]


def test_detect_libs():
    assert set(signing.DEFAULT_PKCS11_LIBS) == {"windows", "linux", "darwin"}
    for p in signing.detect_pkcs11_libs():
        assert os.path.isfile(p)


# --------------------------------------------------------------------------- SoftHSM

SOFTHSM_LIB = next(
    (p for p in ("/usr/lib/softhsm/libsofthsm2.so",
                 "/usr/lib/x86_64-linux-gnu/softhsm/libsofthsm2.so",
                 "/usr/local/lib/softhsm/libsofthsm2.so") if os.path.isfile(p)),
    None,
)


@pytest.fixture(scope="module")
def softhsm(tmp_path_factory, pfx_pair):
    if not shutil.which("softhsm2-util") or not SOFTHSM_LIB:
        pytest.skip("SoftHSM nu este instalat")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    d = tmp_path_factory.mktemp("softhsm")
    (d / "tokens").mkdir()
    conf = d / "softhsm2.conf"
    conf.write_text(f"directories.tokendir = {d / 'tokens'}\nobjectstore.backend = file\n")
    os.environ["SOFTHSM2_CONF"] = str(conf)
    subprocess.run(
        ["softhsm2-util", "--init-token", "--free", "--label", "TestToken",
         "--pin", "1234", "--so-pin", "5678"], check=True, capture_output=True,
    )
    a, _ = pfx_pair
    key, cert, _ = pkcs12.load_key_and_certificates(a, b"parola1")
    key_pem = d / "key.pem"
    key_pem.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    subprocess.run(
        ["softhsm2-util", "--import", str(key_pem), "--token", "TestToken",
         "--label", "Ion Popescu", "--id", "a1b2", "--pin", "1234"],
        check=True, capture_output=True,
    )
    import pkcs11
    from pkcs11 import Attribute, CertificateType, ObjectClass

    lib = pkcs11.lib(SOFTHSM_LIB)
    tok = lib.get_token(token_label="TestToken")
    with tok.open(user_pin="1234", rw=True) as s:
        s.create_object({
            Attribute.CLASS: ObjectClass.CERTIFICATE,
            Attribute.CERTIFICATE_TYPE: CertificateType.X_509,
            Attribute.TOKEN: True,
            Attribute.LABEL: "Ion Popescu",
            Attribute.ID: bytes.fromhex("a1b2"),
            Attribute.VALUE: cert.public_bytes(serialization.Encoding.DER),
            Attribute.SUBJECT: cert.subject.public_bytes(),
        })
    return SOFTHSM_LIB


def test_softhsm_sign(softhsm):
    toks = signing.list_pkcs11_tokens(softhsm)
    assert any(t["label"] == "TestToken" for t in toks)
    certs = signing.list_token_certs(softhsm, "TestToken", "1234")
    assert certs and certs[0]["key_id"] == "a1b2"
    assert certs[0]["email"] == "ion@example.ro"
    with pytest.raises(ValueError):
        signing.list_token_certs(softhsm, "TestToken", "0000")

    pdf = make_pdf(1)
    # selecție automată a certificatului
    s1 = signing.sign_pdf(pdf, method="pkcs11",
                          params={"lib_path": softhsm, "token_label": "TestToken", "pin": "1234"})
    # selecție explicită după key_id, vizibilă
    s2 = signing.sign_pdf(s1, method="pkcs11",
                          params={"lib_path": softhsm, "token_label": "TestToken", "pin": "1234",
                                  "key_id": "a1b2"},
                          visible={"page": 0, "x": 40, "y": 40, "w": 200, "h": 60},
                          reason="Semnare pe token")
    # selecție după etichetă
    s3 = signing.sign_pdf(s2, method="pkcs11",
                          params={"lib_path": softhsm, "token_label": "TestToken", "pin": "1234",
                                  "cert_label": "Ion Popescu"})
    res = signing.validate_pdf(s3)
    assert len(res) == 3
    for r in res:
        assert r["intact"] and r["valid"], r
        assert r["signer_name"] == "Ion Popescu"


# --------------------------------------------------------------------------- CSC (server fals)


@pytest.fixture
def fake_csc(pfx_pair):
    import asyncio
    import base64
    import socket
    import threading

    from aiohttp import web
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, utils
    from cryptography.hazmat.primitives.serialization import pkcs12

    _, b = pfx_pair
    key, cert, _ = pkcs12.load_key_and_certificates(b, b"parola2")
    cert_b64 = base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()
    seen = {}

    def auth_ok(req):
        return req.headers.get("Authorization") == "Bearer TOKEN123"

    async def info(req):
        if not auth_ok(req):
            return web.json_response({"error": "invalid_token"}, status=401)
        return web.json_response({
            "key": {"status": "enabled", "algo": ["1.2.840.113549.1.1.11"], "len": 2048},
            "cert": {"status": "valid", "certificates": [cert_b64]},
            "authMode": "explicit", "SCAL": "2", "multisign": 1,
        })

    async def authorize(req):
        body = await req.json()
        if body.get("PIN") != "4321" or body.get("OTP") != "111111":
            return web.json_response({"error": "invalid_pin"}, status=400)
        seen["auth_hashes"] = body.get("hash")
        return web.json_response({"SAD": "SAD-OK", "expiresIn": 300})

    async def sign_hash(req):
        body = await req.json()
        assert body["SAD"] == "SAD-OK"
        assert body["hash"] == seen["auth_hashes"]
        sigs = [
            base64.b64encode(key.sign(base64.b64decode(h), padding.PKCS1v15(),
                                      utils.Prehashed(hashes.SHA256()))).decode()
            for h in body["hash"]
        ]
        return web.json_response({"signatures": sigs})

    app = web.Application()
    app.router.add_post("/csc/v1/credentials/info", info)
    app.router.add_post("/csc/v1/credentials/authorize", authorize)
    app.router.add_post("/csc/v1/signatures/signHash", sign_hash)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    loop = asyncio.new_event_loop()
    runner = web.AppRunner(app)
    started = threading.Event()

    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runner.setup())
        loop.run_until_complete(web.TCPSite(runner, "127.0.0.1", port).start())
        started.set()
        loop.run_forever()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    started.wait(10)
    yield f"http://127.0.0.1:{port}"
    asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(10)
    loop.call_soon_threadsafe(loop.stop)
    t.join(10)


def test_csc_sign(fake_csc):
    params = {"service_url": fake_csc + "/csc/v1", "access_token": "TOKEN123",
              "credential_id": "cred-1", "pin": "4321", "otp": "111111"}
    out = signing.sign_pdf(make_pdf(1), method="csc", params=params, reason="Cloud",
                           visible={"page": 0, "x": 50, "y": 50, "w": 200, "h": 60})
    res = signing.validate_pdf(out)
    assert len(res) == 1 and res[0]["intact"] and res[0]["valid"], res
    assert res[0]["signer_name"] == "Maria Ionescu"

    with pytest.raises(ValueError):
        signing.sign_pdf(make_pdf(1), method="csc", params={**params, "pin": "0000"})
    with pytest.raises(ValueError):
        signing.sign_pdf(make_pdf(1), method="csc", params={**params, "access_token": "x"})
