"""Diagnostic: listează TOATE certificatele din magazinele Windows,
fără filtre, ca să vedem de ce lista aplicației vine goală.
Rulează din folderul pdf-studio:  python diag_certs.py
"""
import sys
sys.path.insert(0, ".")

from app import winsign
from asn1crypto import x509 as X

ctypes, crypt32, advapi32, ncrypt = winsign._win_libs()
CC, _ = winsign._cert_context_class(ctypes)
winsign._setup_prototypes(ctypes, crypt32, advapi32, ncrypt, CC)


def scan(store_name):
    store = crypt32.CertOpenSystemStoreW(None, store_name)
    print(f"\n=== Magazin '{store_name}'  (handle={store}) ===")
    if not store:
        print("  nu s-a putut deschide")
        return
    total = 0
    withkey = 0
    ctx = crypt32.CertEnumCertificatesInStore(store, None)
    while ctx:
        total += 1
        try:
            der = winsign._der_from_context(ctypes, ctx)
            cert = X.Certificate.load(der)
            cn = winsign._subject_cn(cert)
            iss = winsign._name_attr(cert.issuer, "common_name")
        except Exception as e:
            cn = f"PARSE ERR: {e!r}"
            iss = "?"
        try:
            hk = winsign._context_has_key(crypt32, ctx)
        except Exception as e:
            hk = f"ERR {e!r}"
        if hk is True:
            withkey += 1
        print(f"  {total:2d}. are_cheie={hk!s:5}  '{cn}'  <-- {iss}")
        ctx = crypt32.CertEnumCertificatesInStore(store, ctx)
    crypt32.CertCloseStore(store, 0)
    print(f"  TOTAL={total}  CU_CHEIE={withkey}")


for name in ("MY", "My"):
    try:
        scan(name)
    except Exception as e:
        print(f"Eroare la '{name}': {e!r}")
