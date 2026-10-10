"""Teste pentru semnarea cu certificat din magazinul Windows (``winstore``).

Pe acest sistem (Linux) nu există API-ul Win32, deci apelurile CNG/CAPI reale
nu pot fi testate. Verificăm aici:
  1. că modulul se importă curat pe Linux și ``available()`` este ``False``;
  2. că metoda „winstore” ridică eroarea românească „doar pe Windows”;
  3. că întreaga asamblare CMS/PAdES prin pyHanko este corectă, suprascriind
     ``_raw_sign`` cu o cheie RSA software (``cryptography``) care corespunde
     certificatului. Dacă validarea iese ``intact=True`` și ``valid=True``,
     înseamnă că restul (în afara apelurilor Windows) este corect.
"""

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import signing, winsign  # noqa: E402


def make_pdf(pages=1) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Contract Windows - pagina {i + 1}", fontsize=14)
    data = doc.tobytes()
    doc.close()
    return data


# --------------------------------------------------------------------------- 1 & 2


def test_imports_clean_and_unavailable_on_linux():
    assert winsign.available() is False
    # listarea delegată întoarce listă goală când nu suntem pe Windows
    assert signing.list_windows_certs() == []


def test_winstore_raises_windows_only():
    with pytest.raises(ValueError) as ei:
        signing.sign_pdf(make_pdf(), method="winstore", params={"thumbprint": "AABBCC"})
    assert "doar pe Windows" in str(ei.value)


def test_constructing_signer_on_linux_raises():
    with pytest.raises(ValueError):
        winsign.WindowsStoreSigner("AABBCC")


# --------------------------------------------------------------------------- 3


def _software_signer(common_name="Semnatar Windows", email="win@example.ro"):
    """Un ``WindowsStoreSigner`` cu ``_raw_sign`` software (cheie RSA locală).

    Ocolim ``__init__`` (care cere Windows) și setăm manual ``signing_cert`` /
    ``cert_registry`` dintr-un certificat auto-semnat creat ca pentru .pfx.
    Astfel traversăm exact calea de asamblare CMS/PAdES a lui pyHanko.
    """
    from asn1crypto import x509 as asn1_x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, utils
    from cryptography.hazmat.primitives.serialization import pkcs12, Encoding
    from pyhanko_certvalidator.registry import SimpleCertificateStore

    pfx = signing.make_test_pfx(common_name, email, "parola")
    key, cert, _ = pkcs12.load_key_and_certificates(pfx, b"parola")
    asn1_cert = asn1_x509.Certificate.load(cert.public_bytes(Encoding.DER))

    _HASH = {"sha256": hashes.SHA256, "sha384": hashes.SHA384, "sha512": hashes.SHA512}

    class _SoftwareWindowsSigner(winsign.WindowsStoreSigner):
        def __init__(self):
            # NU apelăm WindowsStoreSigner.__init__ (ar cere Windows);
            # mergem direct la Signer-ul pyHanko.
            self._thumbprint = winsign._sha1_hex(asn1_cert.dump())
            self._cert_ctx = None
            registry = SimpleCertificateStore()
            winsign.Signer.__init__(
                self,
                signing_cert=asn1_cert,
                cert_registry=registry,
                signature_mechanism=self._default_mechanism(asn1_cert),
            )

        def _raw_sign(self, hashed, digest_algorithm, mechanism):
            # semnăm rezumatul deja calculat (Prehashed), ca NCryptSignHash pe RSA
            return key.sign(
                hashed,
                padding.PKCS1v15(),
                utils.Prehashed(_HASH[digest_algorithm]()),
            )

        def __del__(self):  # fără context Win32 de eliberat
            pass

    return _SoftwareWindowsSigner(), asn1_cert


def test_cms_assembly_via_software_key():
    """Dovedește că asamblarea CMS/PAdES (totul în afară de apelurile Windows)
    este corectă: semnăm cu o cheie software prin fluxul real ``_do_sign``."""
    import asyncio

    signer, _cert = _software_signer()
    pdf = make_pdf(1)

    async def run():
        writer = signing._prepare_writer(pdf)
        existing = signing._existing_field_names(writer.prev)
        field = signing._unique_field_name(existing)
        return await signing._do_sign(
            writer, signer, field, existing,
            reason="Aprobare", location="București", contact=None,
            visible={"page": 0, "x": 40, "y": 40, "w": 220, "h": 70},
            timestamp_url=None,
        )

    out = signing._run_async(run())
    assert out.startswith(pdf)  # semnare incrementală

    res = signing.validate_pdf(out)
    assert len(res) == 1
    r = res[0]
    assert r["intact"] is True and r["valid"] is True, r
    assert r["signer_name"] == "Semnatar Windows"
    assert r["signer_email"] == "win@example.ro"
    # semnătura vizibilă a produs un widget pe pagina 0
    doc = fitz.open(stream=out, filetype="pdf")
    try:
        assert any(w.field_name == r["field"] for w in doc[0].widgets())
    finally:
        doc.close()


def test_dry_run_placeholder_no_token():
    """``async_sign_raw(dry_run=True)`` nu trebuie să atingă token-ul (fără PIN)."""
    import asyncio

    signer, _cert = _software_signer()

    # dacă dry-run ar apela _raw_sign, ar arunca (nu există cheie Windows)
    def _boom(*a, **k):
        raise AssertionError("dry_run nu trebuie să semneze efectiv")

    signer._raw_sign = _boom
    placeholder = asyncio.run(signer.async_sign_raw(b"date", "sha256", dry_run=True))
    assert isinstance(placeholder, bytes) and len(placeholder) == 256  # RSA 2048
