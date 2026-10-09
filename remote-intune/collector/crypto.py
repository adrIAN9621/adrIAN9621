"""Criptografie: parole utilizatori (PBKDF2) și criptarea parolelor RustDesk.

Parolele tehnicienilor sunt verificate cu PBKDF2-HMAC-SHA256 (sare per utilizator,
200.000+ iterații). Parolele de acces neasistat RustDesk sunt criptate în repaus
cu Fernet (AES-128-CBC + HMAC), cheia fiind derivată din secretul ``enc_secret``.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken

# Iterații PBKDF2 pentru parolele utilizatorilor web.
PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16
# Sare fixă, la nivel de aplicație, pentru derivarea cheii Fernet din enc_secret.
# Secretul rămâne în config.json; aceasta doar leagă derivarea de aplicație.
_FERNET_KDF_SALT = b"carpatica-feroviar-collector-fernet-v1"
_FERNET_KDF_ITERS = 200_000


# --------------------------------------------------------------------------- #
# Parole utilizatori web (PBKDF2)
# --------------------------------------------------------------------------- #
def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> dict:
    """Întoarce dict cu sare (hex), hash (hex) și numărul de iterații."""
    salt = os.urandom(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return {
        "salt": salt.hex(),
        "hash": dk.hex(),
        "iterations": iterations,
    }


def verify_password(password: str, salt_hex: str, hash_hex: str, iterations: int) -> bool:
    """Verificare în timp constant a parolei unui utilizator web."""
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)


# --------------------------------------------------------------------------- #
# Criptarea parolelor RustDesk în repaus (Fernet)
# --------------------------------------------------------------------------- #
def _derive_fernet_key(enc_secret: str) -> bytes:
    dk = hashlib.pbkdf2_hmac(
        "sha256", enc_secret.encode("utf-8"), _FERNET_KDF_SALT, _FERNET_KDF_ITERS
    )
    return base64.urlsafe_b64encode(dk)


class PasswordCipher:
    """Cifru simetric pentru parolele dispozitivelor, derivat din enc_secret."""

    def __init__(self, enc_secret: str):
        if not enc_secret:
            raise ValueError("enc_secret este obligatoriu pentru criptare.")
        self._fernet = Fernet(_derive_fernet_key(enc_secret))

    def encrypt(self, plaintext: str) -> str:
        token = self._fernet.encrypt((plaintext or "").encode("utf-8"))
        return token.decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise ValueError("Nu s-a putut decripta parola stocată.") from exc
