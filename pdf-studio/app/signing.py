"""Semnare și validare PDF (PAdES) – pyHanko.

Metode de semnare:
  * ``winstore`` – certificat din magazinul Windows „MY” (ca ID-ul digital din
    Adobe Acrobat; token-uri AlfaSign etc. al căror driver înregistrează
    certificatul în Windows). Doar pe Windows.
  * ``pkcs12`` – fișier .pfx/.p12 (certificat + cheie privată)
  * ``pkcs11`` – token USB / smart card (SafeNet, Bit4id, IDPrime, OpenSC ...)
  * ``csc``    – semnătură în cloud (Cloud Signature Consortium API v1/v2)

Toate funcțiile primesc / întorc ``bytes``. Erorile destinate utilizatorului
sunt ridicate ca ``ValueError`` cu mesaj în limba română.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as _dt
import functools
import glob
import logging
import os
import re
import sys
import unicodedata
from io import BytesIO
from typing import Any

from asn1crypto import pem as asn1_pem
from asn1crypto import x509 as asn1_x509

from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields as sig_fields
from pyhanko.sign import signers
from pyhanko.sign.fields import SigFieldSpec, SigSeedSubFilter
from pyhanko.sign.validation.settings import KeyUsageConstraints
from pyhanko.sign.timestamps import HTTPTimeStamper
from pyhanko.sign.validation import async_validate_pdf_signature
from pyhanko.stamp import TextStampStyle
from pyhanko.pdf_utils import layout
from pyhanko.pdf_utils.text import TextBoxStyle
from pyhanko_certvalidator import ValidationContext

log = logging.getLogger(__name__)

from . import winsign

__all__ = [
    "DEFAULT_PKCS11_LIBS",
    "detect_pkcs11_libs",
    "list_pkcs11_tokens",
    "list_token_certs",
    "list_windows_certs",
    "sign_pdf",
    "validate_pdf",
    "make_test_pfx",
]

# ---------------------------------------------------------------------------
# Biblioteci PKCS#11 uzuale în România
# ---------------------------------------------------------------------------

_WIN_SYS = os.environ.get("SystemRoot", r"C:\Windows")
_WIN_PF = os.environ.get("ProgramFiles", r"C:\Program Files")
_WIN_PF86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

DEFAULT_PKCS11_LIBS: dict[str, list[str]] = {
    "windows": [
        # SafeNet / Thales eToken (certSIGN, Trans Sped, DigiSign, AlfaTrust)
        rf"{_WIN_SYS}\System32\eTPKCS11.dll",
        rf"{_WIN_SYS}\System32\eToken.dll",
        rf"{_WIN_SYS}\System32\eTokenPKCS11.dll",
        rf"{_WIN_PF}\SafeNet\Authentication\SAC\x64\eTPKCS11.dll",
        rf"{_WIN_PF86}\SafeNet\Authentication\SAC\x32\eTPKCS11.dll",
        # Bit4id (DigiSign, certSIGN – token-uri miniLector / Digital DNA)
        rf"{_WIN_SYS}\System32\bit4xpki.dll",
        rf"{_WIN_SYS}\System32\bit4ipki.dll",
        rf"{_WIN_SYS}\System32\bit4opki.dll",
        rf"{_WIN_PF}\Bit4id\Universal Middleware\bit4xpki.dll",
        # Gemalto / Thales IDPrime (certSIGN, Trans Sped)
        rf"{_WIN_SYS}\System32\IDPrimePKCS11.dll",
        rf"{_WIN_PF}\Gemalto\IDGo 800 PKCS#11\IDPrimePKCS1164.dll",
        rf"{_WIN_PF86}\Gemalto\IDGo 800 PKCS#11\IDPrimePKCS11.dll",
        rf"{_WIN_PF}\Gemalto\Classic Client\BIN\gclib.dll",
        # Trans Sped (token-uri SafeNet / IDPrime / Longmai)
        rf"{_WIN_SYS}\System32\TransSped\TransSpedP11.dll",
        rf"{_WIN_SYS}\System32\mToken CryptoID\CryptoIDA_pkcs11.dll",
        rf"{_WIN_SYS}\System32\CryptoIDA_pkcs11.dll",
        # AlfaSign / AlfaTrust (token-uri SafeNet / Bit4id / Longmai)
        rf"{_WIN_SYS}\System32\AlfaSignP11.dll",
        rf"{_WIN_SYS}\System32\WDPKCS.dll",
        rf"{_WIN_SYS}\System32\gclib.dll",
        # OpenSC (CEI – carte electronică de identitate, alte carduri)
        rf"{_WIN_SYS}\System32\opensc-pkcs11.dll",
        rf"{_WIN_PF}\OpenSC Project\OpenSC\pkcs11\opensc-pkcs11.dll",
        rf"{_WIN_PF86}\OpenSC Project\OpenSC\pkcs11\opensc-pkcs11.dll",
        # IDEMIA / Oberthur (CEI România)
        rf"{_WIN_PF}\IDEMIA\IDEMIA PKCS#11\pkcs11.dll",
    ],
    "linux": [
        # SafeNet / Thales eToken
        "/usr/lib/libeTPkcs11.so",
        "/usr/lib64/libeTPkcs11.so",
        "/usr/local/lib/libeTPkcs11.so",
        "/usr/lib/libIDPrimePKCS11.so",
        "/usr/lib/x86_64-linux-gnu/libIDPrimePKCS11.so",
        # Bit4id
        "/usr/lib/bit4id/libbit4xpki.so",
        "/usr/lib/libbit4xpki.so",
        "/usr/local/lib/bit4id/libbit4xpki.so",
        "/usr/lib/libbit4ipki.so",
        # Gemalto Classic Client
        "/usr/lib/pkcs11/libgclib.so",
        "/usr/lib/libgclib.so",
        # Trans Sped / Longmai mToken
        "/usr/lib/libmtoken_pkcs11.so",
        "/usr/lib/libgm3000_pkcs11.so",
        # OpenSC
        "/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so",
        "/usr/lib/x86_64-linux-gnu/pkcs11/opensc-pkcs11.so",
        "/usr/lib/aarch64-linux-gnu/opensc-pkcs11.so",
        "/usr/lib64/opensc-pkcs11.so",
        "/usr/lib64/pkcs11/opensc-pkcs11.so",
        "/usr/lib/opensc-pkcs11.so",
        "/usr/lib/pkcs11/opensc-pkcs11.so",
        # SoftHSM (teste)
        "/usr/lib/softhsm/libsofthsm2.so",
        "/usr/lib/x86_64-linux-gnu/softhsm/libsofthsm2.so",
        "/usr/local/lib/softhsm/libsofthsm2.so",
    ],
    "darwin": [
        "/usr/local/lib/libeTPkcs11.dylib",
        "/Library/Frameworks/eToken.framework/Versions/A/libeTPkcs11.dylib",
        "/usr/local/lib/libbit4xpki.dylib",
        "/Library/Bit4id/pkcs11/libbit4xpki.dylib",
        "/usr/local/lib/libIDPrimePKCS11.dylib",
        "/Library/Frameworks/IDPrimePKCS11.framework/Versions/A/libIDPrimePKCS11.dylib",
        "/usr/local/lib/opensc-pkcs11.so",
        "/Library/OpenSC/lib/opensc-pkcs11.so",
        "/opt/homebrew/lib/opensc-pkcs11.so",
        "/opt/homebrew/lib/softhsm/libsofthsm2.so",
        "/usr/local/lib/softhsm/libsofthsm2.so",
    ],
}


def _platform_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def detect_pkcs11_libs() -> list[str]:
    """Căile bibliotecilor PKCS#11 din listă care există pe acest sistem."""
    found: list[str] = []
    for p in DEFAULT_PKCS11_LIBS.get(_platform_key(), []):
        try:
            if os.path.isfile(p) and p not in found:
                found.append(p)
        except OSError:
            continue
    return found


# ---------------------------------------------------------------------------
# Utilitare async (modul apelat din endpoint-uri FastAPI sincrone / threadpool)
# ---------------------------------------------------------------------------

_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="signing-async"
)


def _run_async(coro):
    """Rulează o corutină sincron, fără „event loop already running”.

    Dacă firul curent are deja o buclă activă, corutina e rulată în alt fir
    cu propria buclă (``asyncio.run``)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return _executor.submit(asyncio.run, coro).result()


# ---------------------------------------------------------------------------
# Utilitare certificate
# ---------------------------------------------------------------------------


def _name_attr(name: asn1_x509.Name, attr: str) -> str | None:
    try:
        native = name.native
    except Exception:  # pragma: no cover
        return None
    val = native.get(attr)
    if isinstance(val, list):
        val = val[0] if val else None
    return str(val) if val is not None else None


def _cert_email(cert: asn1_x509.Certificate) -> str | None:
    try:
        san = cert.subject_alt_name_value
        if san is not None:
            for gn in san:
                if gn.name == "rfc822_name":
                    return str(gn.native)
    except Exception:
        pass
    return _name_attr(cert.subject, "email_address")


def _cert_name(cert: asn1_x509.Certificate) -> str | None:
    cn = _name_attr(cert.subject, "common_name")
    if cn:
        return cn
    gn = _name_attr(cert.subject, "given_name")
    sn = _name_attr(cert.subject, "surname")
    full = " ".join(x for x in (gn, sn) if x)
    return full or None


def _iso(d: _dt.datetime | None) -> str | None:
    if d is None:
        return None
    try:
        return d.isoformat()
    except Exception:
        return str(d)


def _load_cert_bytes(data: bytes) -> list[asn1_x509.Certificate]:
    """Încarcă unul sau mai multe certificate DER / PEM."""
    out: list[asn1_x509.Certificate] = []
    if not data:
        return out
    if asn1_pem.detect(data):
        for type_name, _hdr, der in asn1_pem.unarmor(data, multiple=True):
            if type_name == "CERTIFICATE":
                out.append(asn1_x509.Certificate.load(der))
    else:
        cert = asn1_x509.Certificate.load(data)
        cert.native  # forțează parsarea – ridică excepție dacă e invalid
        out.append(cert)
    return out


@functools.lru_cache(maxsize=1)
def _default_trust_roots() -> tuple[asn1_x509.Certificate, ...]:
    """Rădăcini implicite: magazinul sistemului (oscrypto) + certifi."""
    roots: dict[bytes, asn1_x509.Certificate] = {}
    try:
        from oscrypto import trust_list  # type: ignore

        for item in trust_list.get_list():
            cert = item[0] if isinstance(item, tuple) else item
            try:
                if not isinstance(cert, asn1_x509.Certificate):
                    cert = asn1_x509.Certificate.load(cert.asn1.dump())
                roots[cert.sha256] = cert
            except Exception:
                continue
    except Exception as e:  # oscrypto poate eșua cu OpenSSL recent
        log.debug("Magazinul de certificate al sistemului indisponibil: %s", e)
    try:
        import certifi

        with open(certifi.where(), "rb") as f:
            for c in _load_cert_bytes(f.read()):
                roots[c.sha256] = c
    except Exception as e:
        log.debug("certifi indisponibil: %s", e)
    return tuple(roots.values())


# ---------------------------------------------------------------------------
# PKCS#11
# ---------------------------------------------------------------------------


def _p11_lib(lib_path: str):
    import pkcs11

    if not lib_path or not os.path.isfile(lib_path):
        raise ValueError(f"Biblioteca PKCS#11 nu a fost găsită: {lib_path}")
    try:
        return pkcs11.lib(lib_path)
    except Exception as e:
        raise ValueError(
            f"Nu s-a putut încărca biblioteca PKCS#11 ({lib_path}): {e}"
        ) from e


def list_pkcs11_tokens(lib_path: str) -> list[dict]:
    """Token-urile prezente: ``{slot_id, label, manufacturer, serial}``."""
    lib = _p11_lib(lib_path)
    out: list[dict] = []
    try:
        slots = lib.get_slots(token_present=True)
    except Exception as e:
        raise ValueError(f"Eroare la citirea sloturilor PKCS#11: {e}") from e
    for slot in slots:
        try:
            tok = slot.get_token()
        except Exception:
            continue
        serial = tok.serial
        if isinstance(serial, bytes):
            serial = serial.decode("ascii", "replace")
        out.append(
            {
                "slot_id": int(slot.slot_id),
                "label": (tok.label or "").strip(),
                "manufacturer": (tok.manufacturer_id or "").strip(),
                "serial": (serial or "").strip(),
            }
        )
    return out


def _find_token(lib, token_label: str):
    for slot in lib.get_slots(token_present=True):
        try:
            tok = slot.get_token()
        except Exception:
            continue
        if not token_label or (tok.label or "").strip() == token_label.strip():
            return tok
    raise ValueError(f"Token-ul „{token_label}” nu a fost găsit. Este conectat?")


def _open_token_session(lib_path: str, token_label: str, pin: str):
    import pkcs11

    lib = _p11_lib(lib_path)
    tok = _find_token(lib, token_label)
    try:
        return tok.open(user_pin=pin if pin else None)
    except pkcs11.exceptions.PinIncorrect as e:
        raise ValueError("PIN incorect.") from e
    except pkcs11.exceptions.PinLocked as e:
        raise ValueError("PIN-ul este blocat. Contactați emitentul token-ului.") from e
    except pkcs11.exceptions.PKCS11Error as e:
        raise ValueError(f"Nu s-a putut deschide sesiunea pe token: {type(e).__name__} {e}") from e


def _token_certs(session) -> list[dict]:
    from pkcs11 import Attribute, ObjectClass

    priv_ids: set[bytes] = set()
    try:
        for k in session.get_objects({Attribute.CLASS: ObjectClass.PRIVATE_KEY}):
            try:
                priv_ids.add(bytes(k[Attribute.ID]))
            except Exception:
                pass
    except Exception:
        pass
    out = []
    for obj in session.get_objects({Attribute.CLASS: ObjectClass.CERTIFICATE}):
        try:
            der = bytes(obj[Attribute.VALUE])
            cert = asn1_x509.Certificate.load(der)
            cert.native
        except Exception:
            continue
        try:
            label = obj[Attribute.LABEL]
        except Exception:
            label = ""
        try:
            key_id = bytes(obj[Attribute.ID])
        except Exception:
            key_id = b""
        out.append(
            {
                "label": label or "",
                "key_id": key_id.hex(),
                "subject": cert.subject.human_friendly,
                "issuer": cert.issuer.human_friendly,
                "not_after": _iso(cert["tbs_certificate"]["validity"]["not_after"].native),
                "email": _cert_email(cert),
                "_has_key": key_id in priv_ids,
                "_cert": cert,
            }
        )
    return out


def list_token_certs(lib_path: str, token_label: str, pin: str) -> list[dict]:
    """Certificatele de pe token: ``{label, key_id, subject, issuer, not_after, email}``."""
    session = _open_token_session(lib_path, token_label, pin)
    try:
        certs = _token_certs(session)
    finally:
        try:
            session.close()
        except Exception:
            pass
    # certificatele cu cheie privată asociată primele; ascundem câmpurile interne
    certs.sort(key=lambda c: not c["_has_key"])
    return [{k: v for k, v in c.items() if not k.startswith("_")} for c in certs]


def list_windows_certs() -> list[dict]:
    """Certificatele din magazinul Windows „MY” (gol dacă nu suntem pe Windows)."""
    if not winsign.available():
        return []
    return winsign.list_windows_certs()


def _is_signing_cert(cert: asn1_x509.Certificate) -> bool:
    try:
        if cert.ca:
            return False
        ku = cert.key_usage_value
        if ku is None:
            return True
        ku = set(ku.native)
        return bool(ku & {"digital_signature", "non_repudiation"})
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Semnare
# ---------------------------------------------------------------------------

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    rf"{_WIN_SYS}\Fonts\arial.ttf",
    rf"{_WIN_SYS}\Fonts\segoeui.ttf",
    rf"{_WIN_SYS}\Fonts\calibri.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


@functools.lru_cache(maxsize=1)
def _find_font() -> str | None:
    here = os.path.dirname(os.path.abspath(__file__))
    local = glob.glob(os.path.join(here, "static", "fonts", "*.ttf"))
    for p in local + _FONT_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def _ascii_fallback(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def _make_font_factory(font_path: str):
    """Fabrică de fonturi TrueType cu metrici normalizate la 1000 unități/em.

    pyHanko scrie lățimile (/W) și ajustările TJ în unitățile fontului; PDF
    cere 1/1000 em, deci fonturile cu unitsPerEm=2048 (DejaVu, Arial) ar ieși
    cu spațiere dublă. Scalăm fontul HarfBuzz și lățimile la 1000."""
    import dataclasses

    from pyhanko.pdf_utils.font.opentype import GlyphAccumulator, GlyphAccumulatorFactory

    class _ScaledGlyphAccumulator(GlyphAccumulator):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._upem_orig = self.units_per_em
            if self._upem_orig and self._upem_orig != 1000:
                self.hb_font.scale = (1000, 1000)
                self.units_per_em = 1000

        def _get_cid_and_width(self, glyph_id):
            if glyph_id in self._glyphs:
                return self._glyphs[glyph_id]
            cid, width = super()._get_cid_and_width(glyph_id)
            if self._upem_orig and self._upem_orig != 1000:
                width = int(round(width * 1000 / self._upem_orig))
                self._glyphs[glyph_id] = (cid, width)
            return cid, width

    @dataclasses.dataclass(frozen=True)
    class _Factory(GlyphAccumulatorFactory):
        def create_font_engine(self, writer, obj_stream=None):
            with open(self.font_file, "rb") as fh:
                data = fh.read()
            if obj_stream is None and writer.stream_xrefs and self.create_objstream_if_needed:
                obj_stream = writer.prepare_object_stream()
            return _ScaledGlyphAccumulator(
                writer=writer,
                font_handle=BytesIO(data),
                font_size=self.font_size,
                ot_script_tag=self.ot_script_tag,
                ot_language_tag=self.ot_language_tag,
                writing_direction=self.writing_direction,
                bcp47_lang_code=self.bcp47_lang_code,
                obj_stream=obj_stream,
            )

    return _Factory(font_path)


def _stamp_style(reason: str | None, location: str | None) -> tuple[TextStampStyle, dict]:
    lines = ["Semnat digital de:", "%(signer)s", "Data: %(ts)s"]
    params: dict[str, str] = {}
    if reason:
        lines.append("Motiv: %(motiv)s")
        params["motiv"] = reason
    if location:
        lines.append("Locație: %(loc)s")
        params["loc"] = location
    text = "\n".join(lines)
    font_path = _find_font()
    factory = None
    if font_path:
        try:  # necesită pyHanko[opentype] (fonttools + uharfbuzz)
            factory = _make_font_factory(font_path)
        except ImportError:
            factory = None
    if factory is not None:
        box_style = TextBoxStyle(font=factory, font_size=9, leading=11)
    else:  # font standard Courier, fără diacritice
        text = _ascii_fallback(text)
        params = {k: _ascii_fallback(v) for k, v in params.items()}
        box_style = TextBoxStyle(font_size=9, leading=11)
    style = TextStampStyle(
        stamp_text=text,
        text_box_style=box_style,
        timestamp_format="%d.%m.%Y %H:%M:%S %z",
        border_width=1,
        background=None,
        inner_content_layout=layout.SimpleBoxLayoutRule(
            x_align=layout.AxisAlignment.ALIGN_MIN,
            y_align=layout.AxisAlignment.ALIGN_MID,
            margins=layout.Margins.uniform(4),
            inner_content_scaling=layout.InnerScaling.SHRINK_TO_FIT,
        ),
    )
    return style, params


def _existing_field_names(reader: PdfFileReader) -> set[str]:
    names: set[str] = set()
    try:
        for name, _val, _ref in sig_fields.enumerate_sig_fields(reader, filled_status=None):
            names.add(str(name))
    except Exception:
        pass
    try:
        af = reader.root.get("/AcroForm")
        if af is not None:
            for f in af.get_object().get("/Fields", []):
                try:
                    t = f.get_object().get("/T")
                    if t is not None:
                        names.add(str(t))
                except Exception:
                    continue
    except Exception:
        pass
    return names


def _unique_field_name(existing: set[str]) -> str:
    i = 1
    while f"Semnatura{i}" in existing:
        i += 1
    return f"Semnatura{i}"


def _make_csc_auth_manager(session_info, cred_info, http, pin, otp):
    from pyhanko.sign.signers.csc_signer import CSCAuthorizationManager
    import aiohttp

    class _Mgr(CSCAuthorizationManager):
        async def authorize_signature(self, hash_b64s):
            req = self.format_csc_auth_request(
                pin=pin or None,
                otp=otp or None,
                hash_b64s=hash_b64s,  # legăm SAD de hash-uri (necesar la SCAL2)
            )
            url = self.csc_session_info.endpoint_url("credentials/authorize")
            try:
                async with http.post(
                    url,
                    headers=self.auth_headers,
                    json=req,
                    raise_for_status=True,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    data = await resp.json()
            except aiohttp.ClientResponseError as e:
                raise ValueError(
                    f"Serviciul de semnare în cloud a refuzat autorizarea (HTTP {e.status}). "
                    "Verificați PIN-ul / codul OTP."
                ) from e
            except aiohttp.ClientError as e:
                raise ValueError(f"Eroare de comunicare cu serviciul de semnare: {e}") from e
            return self.parse_csc_auth_response(data)

    return _Mgr(session_info, cred_info)


def _csc_session_info(params: dict):
    from pyhanko.sign.signers.csc_signer import CSCServiceSessionInfo

    url = (params.get("service_url") or "").strip().rstrip("/")
    if not url:
        raise ValueError("Lipsește adresa serviciului de semnare în cloud (service_url).")
    if not params.get("credential_id"):
        raise ValueError("Lipsește identificatorul credențialului (credential_id).")
    api_ver = params.get("api_ver") or "v1"
    m = re.search(r"/csc/(v\d+)$", url)
    if m:
        api_ver = m.group(1)
        url = url[: m.start()]
    return CSCServiceSessionInfo(
        service_url=url,
        credential_id=str(params["credential_id"]),
        oauth_token=params.get("access_token") or None,
        api_ver=api_ver,
    )


def _prepare_writer(pdf: bytes) -> IncrementalPdfFileWriter:
    if not pdf:
        raise ValueError("Fișierul PDF este gol.")
    try:
        w = IncrementalPdfFileWriter(BytesIO(pdf), strict=False)
    except Exception as e:
        raise ValueError(f"Fișierul nu este un PDF valid: {e}") from e
    if w.prev.encrypted:
        raise ValueError(
            "PDF-ul este criptat/protejat cu parolă. Eliminați protecția înainte de semnare."
        )
    return w


def sign_pdf(
    pdf: bytes,
    *,
    method: str,
    params: dict,
    field_name: str | None = None,
    reason: str | None = None,
    location: str | None = None,
    contact: str | None = None,
    visible: dict | None = None,
    timestamp_url: str | None = None,
) -> bytes:
    """Semnează PAdES (B-B / B-T) incremental și întoarce PDF-ul semnat."""
    params = params or {}
    method = (method or "").lower().strip()
    if method not in ("pkcs12", "pkcs11", "csc", "winstore"):
        raise ValueError(f"Metodă de semnare necunoscută: {method}")
    return _run_async(
        _async_sign_pdf(
            pdf,
            method=method,
            params=params,
            field_name=field_name,
            reason=reason,
            location=location,
            contact=contact,
            visible=visible,
            timestamp_url=timestamp_url,
        )
    )


async def _async_sign_pdf(
    pdf: bytes,
    *,
    method: str,
    params: dict,
    field_name: str | None,
    reason: str | None,
    location: str | None,
    contact: str | None,
    visible: dict | None,
    timestamp_url: str | None,
) -> bytes:
    writer = _prepare_writer(pdf)
    existing = _existing_field_names(writer.prev)
    if not field_name:
        field_name = _unique_field_name(existing)

    if method == "pkcs12":
        signer = _pkcs12_signer(params)
        return await _do_sign(
            writer, signer, field_name, existing, reason, location, contact, visible, timestamp_url
        )

    if method == "winstore":
        if not winsign.available():
            raise ValueError(
                "Semnarea cu certificat Windows este disponibilă doar pe Windows."
            )
        signer = winsign.WindowsStoreSigner(params.get("thumbprint") or "")
        return await _do_sign(
            writer, signer, field_name, existing, reason, location, contact, visible, timestamp_url
        )

    if method == "pkcs11":
        from pyhanko.sign.pkcs11 import PKCS11Signer

        session = _open_token_session(
            params.get("lib_path") or "", params.get("token_label") or "", params.get("pin") or ""
        )
        try:
            cert_label = params.get("cert_label") or None
            key_id_hex = params.get("key_id") or None
            key_id = None
            if key_id_hex:
                try:
                    key_id = bytes.fromhex(str(key_id_hex))
                except ValueError as e:
                    raise ValueError("key_id trebuie să fie în format hexazecimal.") from e
            signing_cert = None
            if not cert_label and not key_id:
                certs = [c for c in _token_certs(session) if c["_has_key"]]
                certs.sort(key=lambda c: not _is_signing_cert(c["_cert"]))
                if not certs:
                    raise ValueError(
                        "Nu s-a găsit niciun certificat cu cheie privată pe token."
                    )
                chosen = certs[0]
                key_id = bytes.fromhex(chosen["key_id"])
                signing_cert = chosen["_cert"]
            elif key_id and not cert_label:
                for c in _token_certs(session):
                    if c["key_id"] == key_id.hex():
                        signing_cert = c["_cert"]
                        break
            kwargs: dict[str, Any] = dict(
                pkcs11_session=session,
                other_certs_to_pull=None,  # aduce și lanțul CA de pe token
            )
            if signing_cert is not None:
                kwargs["signing_cert"] = signing_cert
                kwargs["key_id"] = key_id
            else:
                kwargs["cert_label"] = cert_label
                if key_id:
                    kwargs["key_id"] = key_id
            try:
                signer = PKCS11Signer(**kwargs)
            except Exception as e:
                raise ValueError(f"Nu s-a putut pregăti semnarea pe token: {e}") from e
            return await _do_sign(
                writer, signer, field_name, existing, reason, location, contact, visible,
                timestamp_url,
            )
        finally:
            try:
                session.close()
            except Exception:
                pass

    # CSC
    import aiohttp
    from pyhanko.sign.signers.csc_signer import CSCSigner, fetch_certs_in_csc_credential

    session_info = _csc_session_info(params)
    async with aiohttp.ClientSession() as http:
        try:
            cred_info = await fetch_certs_in_csc_credential(http, session_info)
        except Exception as e:
            raise ValueError(
                f"Nu s-au putut obține certificatele din serviciul de semnare în cloud: {e}"
            ) from e
        mgr = _make_csc_auth_manager(
            session_info, cred_info, http, params.get("pin"), params.get("otp")
        )
        signer = CSCSigner(http, auth_manager=mgr)
        return await _do_sign(
            writer, signer, field_name, existing, reason, location, contact, visible, timestamp_url
        )


def _pkcs12_signer(params: dict):
    pfx = params.get("pfx")
    if not pfx:
        raise ValueError("Lipsește fișierul certificatului (.pfx / .p12).")
    password = params.get("password")
    pw = password.encode("utf-8") if isinstance(password, str) else password
    try:
        signer = signers.SimpleSigner.load_pkcs12_data(pfx, other_certs=[], passphrase=pw or None)
    except Exception as e:
        signer = None
        err = e
    else:
        err = None
    if signer is None:
        msg = str(err).lower() if err else ""
        if "password" in msg or "mac" in msg or "decrypt" in msg or "invalid" in msg:
            raise ValueError("Parolă incorectă pentru certificatul .pfx sau fișier invalid.")
        raise ValueError(f"Nu s-a putut încărca certificatul .pfx: {err}")
    return signer


async def _do_sign(
    writer, signer, field_name, existing, reason, location, contact, visible, timestamp_url
) -> bytes:
    cert = signer.signing_cert
    signer_name = _cert_name(cert) if cert is not None else None

    meta = signers.PdfSignatureMetadata(
        field_name=field_name,
        reason=reason or None,
        location=location or None,
        contact_info=contact or None,
        name=signer_name,
        md_algorithm="sha256",
        subfilter=SigSeedSubFilter.PADES,
    )

    new_field_spec = None
    stamp_style = None
    text_params = None
    if visible:
        try:
            page = int(visible.get("page", 0))
            x = float(visible["x"])
            y = float(visible["y"])
            w = float(visible["w"])
            h = float(visible["h"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(
                "Poziția semnăturii vizibile este incompletă (page, x, y, w, h)."
            ) from e
        if w <= 0 or h <= 0:
            raise ValueError("Dimensiunile casetei de semnătură trebuie să fie pozitive.")
        try:
            n_pages = int(writer.root["/Pages"]["/Count"])
        except Exception:
            n_pages = None
        if page < 0 or (n_pages is not None and page >= n_pages):
            raise ValueError(f"Pagina {page + 1} nu există în document.")
        stamp_style, text_params = _stamp_style(reason, location)
        if field_name not in existing:
            new_field_spec = SigFieldSpec(
                sig_field_name=field_name,
                on_page=page,
                box=(int(round(x)), int(round(y)), int(round(x + w)), int(round(y + h))),
            )
    elif field_name not in existing:
        new_field_spec = SigFieldSpec(sig_field_name=field_name)  # invizibilă

    timestamper = HTTPTimeStamper(timestamp_url) if timestamp_url else None

    pdf_signer = signers.PdfSigner(
        meta,
        signer=signer,
        timestamper=timestamper,
        stamp_style=stamp_style,
        new_field_spec=new_field_spec,
    )
    out = BytesIO()
    try:
        await pdf_signer.async_sign_pdf(
            writer, output=out, appearance_text_params=text_params or None
        )
    except ValueError:
        raise
    except Exception as e:
        log.exception("Semnarea a eșuat")
        msg = str(e) or type(e).__name__
        if timestamp_url and ("timestamp" in msg.lower() or "tsa" in msg.lower()):
            raise ValueError(f"Serverul de marcă temporală nu a răspuns corect: {msg}") from e
        raise ValueError(f"Semnarea a eșuat: {msg}") from e
    return out.getvalue()


# ---------------------------------------------------------------------------
# Validare
# ---------------------------------------------------------------------------

VALIDATION_ALLOW_FETCHING = False
"""Dacă ``True``, se descarcă CRL/OCSP și certificate intermediare (AIA)."""


def _build_vc(extra_trust_roots: list[bytes] | None) -> tuple[ValidationContext, list[str]]:
    errors: list[str] = []
    roots = list(_default_trust_roots())
    for i, data in enumerate(extra_trust_roots or []):
        try:
            roots.extend(_load_cert_bytes(data))
        except Exception as e:
            errors.append(f"Certificatul de încredere #{i + 1} nu a putut fi citit: {e}")
    vc = ValidationContext(
        trust_roots=roots,
        allow_fetching=VALIDATION_ALLOW_FETCHING,
        revocation_mode="soft-fail",
    )
    return vc, errors


_COVERAGE_RO = {
    "ENTIRE_FILE": "întregul document",
    "ENTIRE_REVISION": "întreaga revizie (au urmat actualizări incrementale)",
    "CONTIGUOUS_BLOCK_FROM_START": "bloc contiguu de la început",
    "UNCLEAR": "neclar",
}

_MODLEVEL_RO = {
    "NONE": "nemodificat",
    "LTA_UPDATES": "doar informații de validare / marcă temporală adăugate",
    "FORM_FILLING": "completare formulare / semnături ulterioare",
    "ANNOTATIONS": "adnotări adăugate",
    "OTHER": "modificări neautorizate",
}


def validate_pdf(pdf: bytes, extra_trust_roots: list[bytes] | None = None) -> list[dict]:
    """Validează toate semnăturile din PDF. Nu aruncă pentru certificate neîncrezute."""
    return _run_async(_async_validate_pdf(pdf, extra_trust_roots))


def _empty_result(field: str | None) -> dict:
    return {
        "field": field,
        "signer_name": None,
        "signer_email": None,
        "signing_time": None,
        "intact": False,
        "valid": False,
        "trusted": False,
        "coverage": "",
        "modification_level": "",
        "timestamp": None,
        "cert_subject": None,
        "cert_issuer": None,
        "cert_not_after": None,
        "summary": "",
        "errors": [],
    }


async def _async_validate_pdf(pdf: bytes, extra_trust_roots) -> list[dict]:
    if not pdf:
        raise ValueError("Fișierul PDF este gol.")
    try:
        reader = PdfFileReader(BytesIO(pdf), strict=False)
    except Exception as e:
        raise ValueError(f"Fișierul nu este un PDF valid: {e}") from e
    if reader.encrypted:
        raise ValueError("PDF-ul este criptat; validarea semnăturilor nu este posibilă.")

    vc, vc_errors = _build_vc(extra_trust_roots)
    try:
        sigs = list(reader.embedded_regular_signatures)
    except Exception as e:
        raise ValueError(f"Semnăturile nu au putut fi citite din PDF: {e}") from e

    kuc = KeyUsageConstraints(
        key_usage={"digital_signature", "non_repudiation"}, match_all_key_usages=False
    )
    results: list[dict] = []
    for sig in sigs:
        try:
            fname = sig.field_name
        except Exception:
            fname = None
        r = _empty_result(fname)
        r["errors"].extend(vc_errors)

        # informații despre semnatar (independent de rezultatul validării)
        try:
            cert = sig.signer_cert
            r["signer_name"] = _cert_name(cert)
            r["signer_email"] = _cert_email(cert)
            r["cert_subject"] = cert.subject.human_friendly
            r["cert_issuer"] = cert.issuer.human_friendly
            r["cert_not_after"] = _iso(cert["tbs_certificate"]["validity"]["not_after"].native)
        except Exception as e:
            r["errors"].append(f"Certificatul semnatarului nu a putut fi citit: {e}")
        try:
            r["signing_time"] = _iso(sig.self_reported_timestamp)
        except Exception:
            pass
        if not r["signer_name"]:
            try:
                n = sig.sig_object.get("/Name")
                if n:
                    r["signer_name"] = str(n)
            except Exception:
                pass

        status = None
        try:
            status = await async_validate_pdf_signature(
                sig,
                signer_validation_context=vc,
                ts_validation_context=vc,
                key_usage_settings=kuc,
            )
        except Exception as e:
            log.debug("Validare eșuată pt %s", fname, exc_info=True)
            r["errors"].append(f"Eroare la validare: {e}")
            # încercăm măcar verificarea integrității
            try:
                sig.compute_integrity_info()
                cov = sig.coverage
                r["coverage"] = getattr(cov, "name", str(cov)) if cov is not None else ""
            except Exception:
                pass

        if status is not None:
            r["intact"] = bool(status.intact)
            r["valid"] = bool(status.valid)
            r["trusted"] = bool(status.trusted)
            cov = status.coverage
            r["coverage"] = cov.name if cov is not None else ""
            try:
                ml = status.modification_level
            except Exception:
                ml = None
            r["modification_level"] = ml.name if ml is not None else ""
            ts = status.timestamp_validity
            if ts is not None:
                try:
                    r["timestamp"] = _iso(ts.timestamp)
                except Exception:
                    pass
            if status.revoked:
                r["errors"].append("Certificatul semnatarului a fost revocat.")
            diff = status.diff_result
            if diff is not None and not hasattr(diff, "modification_level"):
                r["errors"].append(f"Modificare suspectă după semnare: {diff}")
            if status.trust_problem_indic is not None and not status.trusted:
                r["errors"].append(f"Problemă de încredere: {status.trust_problem_indic.name}")

        r["summary"] = _summary_ro(r, status)
        results.append(r)
    return results


def _summary_ro(r: dict, status) -> str:
    parts: list[str] = []
    ml = r.get("modification_level")
    if not r["intact"]:
        parts.append(
            "Document modificat după semnare (conținutul semnat nu mai corespunde)"
        )
    elif not r["valid"]:
        parts.append("Semnătură invalidă criptografic")
    elif ml == "OTHER" or r["coverage"] in ("UNCLEAR", "CONTIGUOUS_BLOCK_FROM_START") and ml != "NONE":
        parts.append("Semnătură validă, dar documentul a fost modificat după semnare")
    elif ml in ("FORM_FILLING", "ANNOTATIONS", "LTA_UPDATES"):
        parts.append(
            "Semnătură validă; după semnare au fost adăugate doar "
            + _MODLEVEL_RO.get(ml, ml.lower())
        )
    else:
        parts.append("Semnătură validă, document nemodificat după semnare")

    if status is not None and getattr(status, "revoked", False):
        parts.append("Certificat revocat")
    elif r["trusted"]:
        parts.append("Certificat de încredere")
    elif r["intact"] and r["valid"]:
        parts.append("Certificat neîncrezut (CA necunoscut)")
    if r["timestamp"]:
        parts.append("Marcă temporală prezentă")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Certificat de test
# ---------------------------------------------------------------------------


def make_test_pfx(common_name: str, email: str, password: str) -> bytes:
    """Certificat auto-semnat (RSA 2048, SHA-256) într-un PKCS#12, pentru teste/demo."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attrs = [
        x509.NameAttribute(NameOID.COUNTRY_NAME, "RO"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PDF Studio (test)"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ]
    if email:
        attrs.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, email))
    name = x509.Name(attrs)
    now = _dt.datetime.now(_dt.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=3 * 365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,  # nonRepudiation
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.EMAIL_PROTECTION, ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
    )
    if email:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.RFC822Name(email)]), critical=False
        )
    cert = builder.sign(key, hashes.SHA256())
    enc = (
        serialization.BestAvailableEncryption(password.encode("utf-8"))
        if password
        else serialization.NoEncryption()
    )
    return pkcs12.serialize_key_and_certificates(
        name=common_name.encode("utf-8"), key=key, cert=cert, cas=None, encryption_algorithm=enc
    )
