"""Semnare PDF cu un certificat din magazinul de certificate Windows ("MY").

Aceasta este echivalentul semnării cu „ID digital” din Adobe Acrobat pe
Windows: certificatul (și cheia privată) locuiesc în magazinul personal al
utilizatorului Windows. Un token USB (de ex. AlfaSign) al cărui middleware
înregistrează certificatul prin CSP/KSP în magazinul „MY” devine astfel
selectabil, iar PIN-ul este cerut de Windows / middleware la momentul semnării.

Modulul este Windows-only, dar **trebuie să se importe curat pe orice platformă**
(Linux inclus): tot accesul la ``ctypes.windll`` / API-ul Win32 este izolat în
interiorul funcțiilor, niciodată la nivel de modul. Pe alte platforme
``available()`` întoarce ``False`` și orice încercare de semnare ridică o
``ValueError`` în limba română.

Operațiile criptografice efective (CNG / NCrypt și CryptoAPI vechi) sunt
izolate în :meth:`WindowsStoreSigner._raw_sign` și în helperele cu prefix
``_win_``. Acestea NU pot fi testate pe acest Linux – sunt marcate explicit cu
„needs testing on Windows with the real token”. Restul (asamblarea CMS/PAdES
prin pyHanko) este acoperit de teste printr-un ``_raw_sign`` software.
"""

from __future__ import annotations

import hashlib
import sys
from typing import Any

from asn1crypto import x509 as asn1_x509
from asn1crypto import algos as asn1_algos

from pyhanko.sign.signers.pdf_cms import Signer, SignedDigestAlgorithm
from pyhanko_certvalidator.registry import SimpleCertificateStore

__all__ = ["available", "list_windows_certs", "WindowsStoreSigner"]


# ---------------------------------------------------------------------------
# Constante Win32 (crypt32 / advapi32 / ncrypt)
# ---------------------------------------------------------------------------

_X509_ASN_ENCODING = 0x00000001
_PKCS_7_ASN_ENCODING = 0x00010000
_CERT_ENCODING = _X509_ASN_ENCODING | _PKCS_7_ASN_ENCODING

_CERT_KEY_PROV_INFO_PROP_ID = 2
_CERT_SHA1_HASH_PROP_ID = 3

# CryptAcquireCertificatePrivateKey
_CRYPT_ACQUIRE_PREFER_NCRYPT_KEY_FLAG = 0x00010000
_CRYPT_ACQUIRE_COMPARE_KEY_FLAG = 0x00000004
_CERT_NCRYPT_KEY_SPEC = 0xFFFFFFFF
_AT_KEYEXCHANGE = 1
_AT_SIGNATURE = 2

# NCrypt
_NCRYPT_PAD_PKCS1_FLAG = 0x00000002

# CryptoAPI (CAPI) legacy
_HP_HASHVAL = 0x0002
_CALG = {
    "sha1": 0x00008004,
    "sha256": 0x0000800C,
    "sha384": 0x0000800D,
    "sha512": 0x0000800E,
}

# BCrypt / NCrypt digest algorithm identifiers (pentru BCRYPT_PKCS1_PADDING_INFO)
_BCRYPT_ALGID = {
    "sha1": "SHA1",
    "sha256": "SHA256",
    "sha384": "SHA384",
    "sha512": "SHA512",
}

# coduri de eroare uzuale la anulare / PIN greșit
_PIN_CANCEL_CODES = {
    0x8010006E,  # SCARD_W_CANCELLED_BY_USER
    0x80100022,  # SCARD_E_CANCELLED
    0x80090016,  # NTE_BAD_KEYSET
    0x8009000D,  # NTE_NO_KEY
    0x80090010,  # NTE_PERM
    0x80100017,  # SCARD_E_NO_SMARTCARD / removed
    0x8010006B,  # SCARD_W_WRONG_CHV (PIN greșit)
    0x8010006C,  # SCARD_W_CHV_BLOCKED
}


def available() -> bool:
    """``True`` doar pe Windows (win32)."""
    return sys.platform.startswith("win")


def _require_windows() -> None:
    if not available():
        raise ValueError(
            "Semnarea cu certificat Windows este disponibilă doar pe Windows."
        )


# ---------------------------------------------------------------------------
# Structuri ctypes – definite în interiorul funcțiilor (import curat pe Linux)
# ---------------------------------------------------------------------------


def _win_libs():
    """Încarcă bibliotecile Win32. Doar pe Windows."""
    import ctypes
    from ctypes import wintypes  # noqa: F401 – necesar pe Windows

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    try:
        ncrypt = ctypes.WinDLL("ncrypt", use_last_error=True)
    except OSError:
        ncrypt = None
    return ctypes, crypt32, advapi32, ncrypt


def _cert_context_class(ctypes):
    from ctypes import wintypes

    class CRYPT_INTEGER_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    class CERT_CONTEXT(ctypes.Structure):
        _fields_ = [
            ("dwCertEncodingType", wintypes.DWORD),
            ("pbCertEncoded", ctypes.POINTER(ctypes.c_byte)),
            ("cbCertEncoded", wintypes.DWORD),
            ("pCertInfo", ctypes.c_void_p),
            ("hCertStore", ctypes.c_void_p),
        ]

    return CERT_CONTEXT, CRYPT_INTEGER_BLOB


def _der_from_context(ctypes, ctx_ptr) -> bytes:
    ctx = ctx_ptr.contents
    return bytes(bytearray(ctx.pbCertEncoded[: ctx.cbCertEncoded]))


def _context_has_key(crypt32, ctx_ptr) -> bool:
    """True dacă certificatul are CERT_KEY_PROV_INFO_PROP_ID (cheie privată asociată).

    NU achiziționează cheia – deci nu apare niciun prompt de PIN la listare.
    """
    import ctypes
    from ctypes import wintypes

    cb = wintypes.DWORD(0)
    ok = crypt32.CertGetCertificateContextProperty(
        ctx_ptr, _CERT_KEY_PROV_INFO_PROP_ID, None, ctypes.byref(cb)
    )
    return bool(ok) and cb.value > 0


def _sha1_hex(der: bytes) -> str:
    return hashlib.sha1(der).hexdigest().upper()


# ---------------------------------------------------------------------------
# Parsarea metadatelor certificatului (partajat cu signing.py prin asn1crypto)
# ---------------------------------------------------------------------------


def _name_attr(name: asn1_x509.Name, attr: str):
    try:
        val = name.native.get(attr)
    except Exception:
        return None
    if isinstance(val, list):
        val = val[0] if val else None
    return str(val) if val is not None else None


def _subject_cn(cert: asn1_x509.Certificate) -> str:
    cn = _name_attr(cert.subject, "common_name")
    if cn:
        return cn
    try:
        return cert.subject.human_friendly
    except Exception:
        return ""


def _cert_email(cert: asn1_x509.Certificate):
    try:
        san = cert.subject_alt_name_value
        if san is not None:
            for gn in san:
                if gn.name == "rfc822_name":
                    return str(gn.native)
    except Exception:
        pass
    return _name_attr(cert.subject, "email_address")


def _iso(d):
    if d is None:
        return None
    try:
        return d.isoformat()
    except Exception:
        return str(d)


def _is_qualified_guess(cert: asn1_x509.Certificate) -> bool:
    """Euristică: cheie pentru semnătură (nonRepudiation / digitalSignature)."""
    try:
        ku = cert.key_usage_value
        if ku is None:
            return False
        return bool(set(ku.native) & {"non_repudiation", "digital_signature"})
    except Exception:
        return False


def _has_non_repudiation(cert: asn1_x509.Certificate) -> bool:
    try:
        ku = cert.key_usage_value
        return ku is not None and "non_repudiation" in set(ku.native)
    except Exception:
        return False


def _cert_meta(cert: asn1_x509.Certificate, der: bytes) -> dict:
    tbs = cert["tbs_certificate"]
    return {
        "thumbprint": _sha1_hex(der),
        "subject": _subject_cn(cert),
        "issuer": _name_attr(cert.issuer, "common_name") or cert.issuer.human_friendly,
        "not_before": _iso(tbs["validity"]["not_before"].native),
        "not_after": _iso(tbs["validity"]["not_after"].native),
        "serial": format(int(tbs["serial_number"].native), "x").upper(),
        "email": _cert_email(cert),
        "has_key": True,
        "is_qualified_guess": _is_qualified_guess(cert),
    }


# ---------------------------------------------------------------------------
# Listarea certificatelor din magazinul „MY”
# ---------------------------------------------------------------------------


def list_windows_certs() -> list[dict]:
    """Certificatele din magazinul personal Windows („MY”) care au cheie privată.

    Întoarce dicționare cu: ``thumbprint, subject, issuer, not_before, not_after,
    serial, email, has_key, is_qualified_guess``. Certificatele de semnătură
    (nonRepudiation) sunt puse primele. Nu se achiziționează nicio cheie, deci
    nu apare niciun prompt de PIN.
    """
    _require_windows()
    ctypes, crypt32, _advapi32, _ncrypt = _win_libs()
    CERT_CONTEXT, _ = _cert_context_class(ctypes)
    crypt32.CertEnumCertificatesInStore.restype = ctypes.POINTER(CERT_CONTEXT)
    crypt32.CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    store = crypt32.CertOpenSystemStoreW(None, "MY")
    if not store:
        err = ctypes.get_last_error()
        raise ValueError(f"Nu s-a putut deschide magazinul de certificate Windows (cod {err}).")

    out: list[dict] = []
    try:
        ctx = crypt32.CertEnumCertificatesInStore(store, None)
        while ctx:
            try:
                if _context_has_key(crypt32, ctx):
                    der = _der_from_context(ctypes, ctx)
                    cert = asn1_x509.Certificate.load(der)
                    cert.native  # forțează parsarea
                    out.append(_cert_meta(cert, der))
            except Exception:
                pass
            ctx = crypt32.CertEnumCertificatesInStore(store, ctx)
    finally:
        # CERT_CLOSE_STORE_CHECK_FLAG = 0 -> eliberare simplă
        crypt32.CertCloseStore(store, 0)

    out.sort(key=lambda c: not c["is_qualified_guess"])
    return out


# ---------------------------------------------------------------------------
# Signer pyHanko peste magazinul Windows
# ---------------------------------------------------------------------------


class WindowsStoreSigner(Signer):
    """Signer pyHanko care folosește o cheie din magazinul „MY” al Windows.

    Construit dintr-un ``thumbprint`` (SHA1 hex). La construcție se localizează
    contextul certificatului, se setează ``signing_cert`` și ``cert_registry``
    (lanțul găsit în magazin). Semnarea efectivă se face prin NCrypt (CNG) sau
    CryptoAPI vechi, cerând PIN-ul prin Windows / middleware-ul token-ului.
    """

    def __init__(self, thumbprint: str):
        _require_windows()
        tp = (thumbprint or "").replace(" ", "").replace(":", "").upper()
        if not tp:
            raise ValueError("Lipsește amprenta (thumbprint) certificatului Windows.")
        self._thumbprint = tp
        # contextul certificatului rămâne „duplicat” (deținut de noi) pe durata vieții
        self._cert_ctx = None  # PCERT_CONTEXT – eliberat în __del__

        signing_cert, registry = self._load_from_store(tp)
        mechanism = self._default_mechanism(signing_cert)
        super().__init__(
            signing_cert=signing_cert,
            cert_registry=registry,
            signature_mechanism=mechanism,
        )

    # ---- construcție / căutare în magazin (Windows-only) -------------------

    def _load_from_store(self, thumbprint: str):
        """Localizează certificatul + lanțul în magazinul „MY”. Windows-only.

        needs testing on Windows with the real token.
        """
        ctypes, crypt32, _advapi32, _ncrypt = self._libs = _win_libs()
        CERT_CONTEXT, _ = _cert_context_class(ctypes)
        crypt32.CertEnumCertificatesInStore.restype = ctypes.POINTER(CERT_CONTEXT)
        crypt32.CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        crypt32.CertDuplicateCertificateContext.restype = ctypes.POINTER(CERT_CONTEXT)
        crypt32.CertDuplicateCertificateContext.argtypes = [ctypes.c_void_p]

        store = crypt32.CertOpenSystemStoreW(None, "MY")
        if not store:
            raise ValueError("Nu s-a putut deschide magazinul de certificate Windows.")

        all_certs: list[tuple[bytes, asn1_x509.Certificate]] = []
        found_ctx = None
        signing_cert = None
        try:
            ctx = crypt32.CertEnumCertificatesInStore(store, None)
            while ctx:
                try:
                    der = _der_from_context(ctypes, ctx)
                    cert = asn1_x509.Certificate.load(der)
                    all_certs.append((der, cert))
                    if found_ctx is None and _sha1_hex(der) == thumbprint:
                        # păstrăm o copie proprie a contextului pentru semnare
                        found_ctx = crypt32.CertDuplicateCertificateContext(ctx)
                        signing_cert = cert
                except Exception:
                    pass
                ctx = crypt32.CertEnumCertificatesInStore(store, ctx)
        finally:
            crypt32.CertCloseStore(store, 0)

        if signing_cert is None or not found_ctx:
            raise ValueError(
                "Certificatul selectat nu a fost găsit în magazinul Windows. "
                "Reconectați token-ul și reîncărcați lista."
            )
        self._cert_ctx = found_ctx

        registry = SimpleCertificateStore()
        chain = self._build_chain(signing_cert, [c for _d, c in all_certs])
        for c in chain:
            try:
                registry.register(c)
            except Exception:
                pass
        return signing_cert, registry

    @staticmethod
    def _build_chain(leaf: asn1_x509.Certificate, pool: list) -> list:
        """Lanț de CA găsit în magazin (best-effort), fără frunza însăși."""
        by_subject: dict[bytes, asn1_x509.Certificate] = {}
        for c in pool:
            try:
                by_subject[c.subject.dump()] = c
            except Exception:
                pass
        chain: list = []
        seen: set[bytes] = set()
        cur = leaf
        for _ in range(16):  # limită de siguranță împotriva buclelor
            try:
                issuer_key = cur.issuer.dump()
                self_key = cur.subject.dump()
            except Exception:
                break
            if issuer_key == self_key:  # auto-semnat / rădăcină
                break
            parent = by_subject.get(issuer_key)
            if parent is None or parent.sha256 in seen:
                break
            chain.append(parent)
            seen.add(parent.sha256)
            cur = parent
        return chain

    @staticmethod
    def _default_mechanism(cert: asn1_x509.Certificate):
        """Mecanism implicit: RSA PKCS#1 v1.5 cu SHA-256; EC -> lăsăm pyHanko să decidă."""
        try:
            algo = cert.public_key.algorithm
        except Exception:
            algo = "rsa"
        if algo == "rsa":
            return SignedDigestAlgorithm({"algorithm": "sha256_rsa"})
        return None  # EC / alte -> imputat din digest la semnare

    # ---- semnare ----------------------------------------------------------

    async def async_sign_raw(
        self, data: bytes, digest_algorithm: str, dry_run: bool = False
    ) -> bytes:
        """Semnează ``data`` (digest-ul ``digest_algorithm``) cu cheia din magazin.

        La ``dry_run`` NU se atinge token-ul (niciun PIN), se întoarce un
        substituent de dimensiune corectă pentru rezervarea spațiului.
        """
        alg = (digest_algorithm or "sha256").lower()
        if dry_run:
            return self._placeholder_signature()
        try:
            hashed = hashlib.new(alg, data).digest()
        except (ValueError, TypeError) as e:
            raise ValueError(f"Algoritm de rezumat nesuportat: {digest_algorithm}") from e
        mechanism = self.get_signature_mechanism_for_digest(alg)
        return self._raw_sign(hashed, alg, mechanism)

    def _placeholder_signature(self) -> bytes:
        """Dimensiunea aproximativă a semnăturii brute, pentru dry-run."""
        try:
            algo = self.signing_cert.public_key.algorithm
            bits = self.signing_cert.public_key.bit_size
        except Exception:
            algo, bits = "rsa", 2048
        if algo == "rsa":
            return b"\x00" * ((bits + 7) // 8)
        # ECDSA -> DER SEQUENCE a doi INTEGER; supraestimăm puțin
        n = (bits + 7) // 8
        return b"\x00" * (2 * (n + 3) + 4)

    def _key_algorithm(self) -> str:
        try:
            return self.signing_cert.public_key.algorithm
        except Exception:
            return "rsa"

    def _raw_sign(self, hashed: bytes, digest_algorithm: str, mechanism) -> bytes:
        """Produce semnătura brută peste ``hashed``.

        Implementarea reală folosește CNG (NCrypt) sau CryptoAPI vechi din
        Windows și cere PIN-ul token-ului. Este izolată aici pentru a putea fi
        suprascrisă în teste cu o cheie software.

        needs testing on Windows with the real token.
        """
        _require_windows()
        return self._win_raw_sign(hashed, digest_algorithm)

    # ---- implementarea Win32 (needs testing on Windows with real token) ----

    def _win_raw_sign(self, hashed: bytes, digest_algorithm: str) -> bytes:
        """Achiziționează cheia și semnează prin NCrypt sau CAPI. Windows-only."""
        import ctypes
        from ctypes import wintypes

        ctypes_mod, crypt32, _advapi32, ncrypt = getattr(self, "_libs", None) or _win_libs()

        h_key = ctypes.c_void_p(0)
        key_spec = wintypes.DWORD(0)
        caller_free = wintypes.BOOL(0)

        crypt32.CryptAcquireCertificatePrivateKey.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.BOOL),
        ]
        # IMPORTANT: NU folosim CRYPT_ACQUIRE_SILENT_FLAG. Pentru conturile de
        # semnare la distanță (STS, AlfaSign cloud etc.) KSP/CSP-ul furnizorului
        # trebuie să poată afișa propriul dialog interactiv (e-mail + parolă +
        # cod Google Authenticator + PIN) și semnează pe un HSM remote.
        ok = crypt32.CryptAcquireCertificatePrivateKey(
            self._cert_ctx,
            _CRYPT_ACQUIRE_PREFER_NCRYPT_KEY_FLAG,
            None,
            ctypes.byref(h_key),
            ctypes.byref(key_spec),
            ctypes.byref(caller_free),
        )
        if not ok or not h_key.value:
            self._raise_pin_error(ctypes.get_last_error())

        try:
            if key_spec.value == _CERT_NCRYPT_KEY_SPEC:
                return self._ncrypt_sign(
                    ctypes, ncrypt, h_key, hashed, digest_algorithm
                )
            return self._capi_sign(
                ctypes, _advapi32, h_key, key_spec.value, hashed, digest_algorithm
            )
        finally:
            if caller_free.value:
                if key_spec.value == _CERT_NCRYPT_KEY_SPEC and ncrypt is not None:
                    ncrypt.NCryptFreeObject(h_key)
                else:
                    _advapi32.CryptReleaseContext(h_key, 0)

    def _ncrypt_sign(self, ctypes, ncrypt, h_key, hashed, digest_algorithm) -> bytes:
        """Semnare CNG. RSA -> PKCS#1 v1.5; EC -> raw r||s convertit în DER."""
        from ctypes import wintypes

        if ncrypt is None:
            raise ValueError("Biblioteca CNG (ncrypt.dll) nu este disponibilă.")

        is_rsa = self._key_algorithm() == "rsa"
        buf = (ctypes.c_byte * len(hashed)).from_buffer_copy(hashed)
        out_len = wintypes.DWORD(0)

        if is_rsa:
            # BCRYPT_PKCS1_PADDING_INFO { LPCWSTR pszAlgId }
            alg_id = _BCRYPT_ALGID.get(digest_algorithm)
            if alg_id is None:
                raise ValueError(f"Algoritm de rezumat nesuportat: {digest_algorithm}")

            class BCRYPT_PKCS1_PADDING_INFO(ctypes.Structure):
                _fields_ = [("pszAlgId", wintypes.LPCWSTR)]

            pad = BCRYPT_PKCS1_PADDING_INFO(alg_id)
            p_pad = ctypes.byref(pad)
            flags = _NCRYPT_PAD_PKCS1_FLAG
        else:
            p_pad = None
            flags = 0

        # prima trecere: dimensiunea semnăturii
        status = ncrypt.NCryptSignHash(
            h_key, p_pad, buf, len(hashed), None, 0, ctypes.byref(out_len), flags
        )
        if status != 0:
            self._raise_pin_error(status & 0xFFFFFFFF)
        sig = (ctypes.c_byte * out_len.value)()
        status = ncrypt.NCryptSignHash(
            h_key, p_pad, buf, len(hashed), sig, out_len.value,
            ctypes.byref(out_len), flags,
        )
        if status != 0:
            self._raise_pin_error(status & 0xFFFFFFFF)
        raw = bytes(bytearray(sig[: out_len.value]))

        if is_rsa:
            return raw
        # EC: raw este r||s (format P1363) -> DER ECDSA-Sig-Value
        return asn1_algos.DSASignature.from_p1363(raw).dump()

    def _capi_sign(self, ctypes, advapi32, h_prov, key_spec, hashed, digest_algorithm) -> bytes:
        """Semnare CryptoAPI vechi (HCRYPTPROV). Doar RSA. Rezultat big-endian."""
        from ctypes import wintypes

        calg = _CALG.get(digest_algorithm)
        if calg is None:
            raise ValueError(f"Algoritm de rezumat nesuportat (CAPI): {digest_algorithm}")

        h_hash = ctypes.c_void_p(0)
        if not advapi32.CryptCreateHash(h_prov, calg, 0, 0, ctypes.byref(h_hash)):
            self._raise_pin_error(ctypes.get_last_error())
        try:
            buf = (ctypes.c_byte * len(hashed)).from_buffer_copy(hashed)
            # injectăm valoarea rezumatului calculat de noi
            if not advapi32.CryptSetHashParam(h_hash, _HP_HASHVAL, buf, 0):
                self._raise_pin_error(ctypes.get_last_error())
            cb = wintypes.DWORD(0)
            key_spec = key_spec or _AT_SIGNATURE
            if not advapi32.CryptSignHashW(
                h_hash, key_spec, None, 0, None, ctypes.byref(cb)
            ):
                self._raise_pin_error(ctypes.get_last_error())
            sig = (ctypes.c_byte * cb.value)()
            if not advapi32.CryptSignHashW(
                h_hash, key_spec, None, 0, sig, ctypes.byref(cb)
            ):
                self._raise_pin_error(ctypes.get_last_error())
            raw = bytes(bytearray(sig[: cb.value]))
            # CAPI întoarce semnătura în little-endian -> o inversăm (RSA)
            return raw[::-1]
        finally:
            advapi32.CryptDestroyHash(h_hash)

    def _raise_pin_error(self, code: int) -> None:
        code &= 0xFFFFFFFF
        if code in _PIN_CANCEL_CODES:
            raise ValueError("Semnarea a fost anulată sau PIN greșit.")
        raise ValueError(
            f"Semnarea cu certificatul Windows a eșuat (cod 0x{code:08X}). "
            "Verificați token-ul și PIN-ul."
        )

    def __del__(self):  # eliberăm contextul duplicat
        ctx = getattr(self, "_cert_ctx", None)
        if ctx:
            try:
                import ctypes

                ctypes.WinDLL("crypt32").CertFreeCertificateContext(ctx)
            except Exception:
                pass
            self._cert_ctx = None
