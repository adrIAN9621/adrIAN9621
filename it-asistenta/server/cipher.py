"""Criptarea parolelor de acces nesupravegheat (RustDesk) în repaus.

Parolele RustDesk raportate de laptopuri sunt criptate cu Fernet (AES-128-CBC +
HMAC), cheia fiind derivată din ``enc_secret`` (config.json). Parolele
tehnicienilor rămân hash-uite cu PBKDF2 în db.py — acest modul e doar pentru
parolele dispozitivelor, care trebuie recuperate în clar de tehnician.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

_KDF_SALT = b"carpatica-feroviar-asistenta-fernet-v1"
_KDF_ITERS = 200_000


def _derive_key(enc_secret: str) -> bytes:
    dk = hashlib.pbkdf2_hmac("sha256", enc_secret.encode("utf-8"), _KDF_SALT, _KDF_ITERS)
    return base64.urlsafe_b64encode(dk)


class PasswordCipher:
    """Cifru simetric pentru parolele dispozitivelor, derivat din enc_secret."""

    def __init__(self, enc_secret: str):
        if not enc_secret:
            raise ValueError("enc_secret este obligatoriu pentru criptare.")
        self._fernet = Fernet(_derive_key(enc_secret))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt((plaintext or "").encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise ValueError("Nu s-a putut decripta parola stocată.") from exc
