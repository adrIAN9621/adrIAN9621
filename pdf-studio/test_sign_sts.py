"""Test real: semnează un PDF cu certificatul din Windows (STS/AlfaSign).
La rulare, furnizorul (STS) afișează fereastra lui: email + parolă + cod
Google Authenticator + PIN. Rezultatul se salvează în test_semnat.pdf și se
validează.  Rulează din folderul pdf-studio:  python test_sign_sts.py
"""
import sys, json
sys.path.insert(0, ".")

import fitz
from app import signing

certs = signing.list_windows_certs()
print("Certificate găsite în Windows:")
for c in certs:
    print(f"  - {c['subject']}  <-- {c['issuer']}  (până la {c['not_after']})")
if not certs:
    raise SystemExit("Niciun certificat cu cheie privată în magazinul Windows.")

# alegem certificatul STS dacă există, altfel primul
sts = next((c for c in certs if "STS" in (c.get("issuer") or "")), certs[0])
print(f"\n>>> Semnez cu: {sts['subject']} / {sts['issuer']}")
print(">>> Dacă apare fereastra STS, introduceți email/parolă/cod/PIN...\n")

doc = fitz.open()
doc.new_page().insert_text((72, 72), "Test semnare STS - Carpatica Feroviar")
pdf = doc.tobytes()

signed = signing.sign_pdf(
    pdf,
    method="winstore",
    params={"thumbprint": sts["thumbprint"]},
    reason="Test semnare",
    location="București",
)
with open("test_semnat.pdf", "wb") as f:
    f.write(signed)
print("OK -> am salvat test_semnat.pdf\n")

print("Rezultat validare:")
print(json.dumps(signing.validate_pdf(signed), ensure_ascii=False, indent=2))
