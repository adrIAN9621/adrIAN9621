"""Linie de comandă pentru colector: pornire server și administrare."""
from __future__ import annotations

import argparse
import datetime
import getpass
import secrets
import sys
from pathlib import Path

from .config import BASE_DIR, ConfigError, load_config, write_default_config
from .crypto import PBKDF2_ITERATIONS, hash_password
from .db import Database


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def cmd_run(args: argparse.Namespace) -> int:
    import uvicorn

    from .app import create_app

    cfg = load_config(args.config)
    try:
        cfg.validate_for_serve()
    except ConfigError as exc:
        _eprint(f"[EROARE] {exc}")
        return 2

    app = create_app(cfg)
    ssl_kwargs = {}
    if cfg.tls_enabled:
        cert, key = cfg.resolve_tls_paths()
        ssl_kwargs = {"ssl_certfile": cert, "ssl_keyfile": key}
        scheme = "https"
    else:
        scheme = "http"
        _eprint(
            "[AVERTISMENT] Pornire fără TLS (allow_insecure=true). "
            "Folosiți acest mod DOAR pentru testare locală."
        )
    print(f"Colector pornit pe {scheme}://{cfg.host}:{cfg.port}  (DB: {cfg.db_path})")
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info", **ssl_kwargs)
    return 0


def cmd_adduser(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db = Database(cfg.db_path)
    username = args.name.strip()
    if not username:
        _eprint("[EROARE] Numele de utilizator nu poate fi gol.")
        return 2
    if db.get_user(username) is not None:
        _eprint(f"[INFO] Utilizatorul '{username}' există deja; parola va fi actualizată.")
    pw1 = getpass.getpass("Parolă nouă: ")
    pw2 = getpass.getpass("Confirmați parola: ")
    if pw1 != pw2:
        _eprint("[EROARE] Parolele nu coincid.")
        return 2
    if len(pw1) < 8:
        _eprint("[EROARE] Parola trebuie să aibă minim 8 caractere.")
        return 2
    h = hash_password(pw1, iterations=PBKDF2_ITERATIONS)
    db.add_user(username, h["salt"], h["hash"], h["iterations"])
    print(f"Utilizatorul '{username}' a fost salvat (PBKDF2-SHA256, {h['iterations']} iterații).")
    return 0


def cmd_deluser(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db = Database(cfg.db_path)
    if db.delete_user(args.name.strip()):
        print(f"Utilizatorul '{args.name}' a fost șters.")
        return 0
    _eprint(f"[EROARE] Utilizatorul '{args.name}' nu există.")
    return 1


def cmd_gentoken(args: argparse.Namespace) -> int:
    token = secrets.token_urlsafe(32)
    print(token)
    _eprint(
        "Copiați acest token în config.json ('ingest_token') ȘI în "
        "remediation/Remediate-ReportDeviceInfo.ps1 ($REPORT_TOKEN)."
    )
    return 0


def cmd_gencert(args: argparse.Namespace) -> int:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    cfg = load_config(args.config)
    cert_path, key_path = cfg.resolve_tls_paths()
    if not cfg.certfile:
        cert_path = str(BASE_DIR / "certs" / "server.crt")
        key_path = str(BASE_DIR / "certs" / "server.key")
    Path(cert_path).parent.mkdir(parents=True, exist_ok=True)
    Path(key_path).parent.mkdir(parents=True, exist_ok=True)

    hostname = args.hostname or "rustdesk.carpatica.local"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Carpatica Feroviar"),
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    Path(key_path).write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    Path(cert_path).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print(f"Certificat autosemnat generat pentru '{hostname}':")
    print(f"  cert: {cert_path}")
    print(f"  cheie: {key_path}")
    _eprint(
        "Certificat intern autosemnat (valabil ~27 luni). Distribuiți-l ca "
        "autoritate de încredere pe laptopuri sau folosiți un CA intern."
    )
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    path = write_default_config(args.config)
    print(f"Fișier de configurare creat: {path}")
    _eprint("Generat 'ingest_token' și 'enc_secret' aleatoriu. Rulați apoi 'gencert' și 'adduser'.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m collector",
        description="Colector RustDesk – Carpatica Feroviar",
    )
    parser.add_argument("--config", help="cale către config.json", default=None)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="pornește serverul web (implicit)")

    p_add = sub.add_parser("adduser", help="adaugă/actualizează un tehnician")
    p_add.add_argument("name", help="nume utilizator")

    p_del = sub.add_parser("deluser", help="șterge un tehnician")
    p_del.add_argument("name", help="nume utilizator")

    sub.add_parser("gentoken", help="generează un token de ingestie aleator")

    p_cert = sub.add_parser("gencert", help="generează certificat TLS autosemnat")
    p_cert.add_argument("--hostname", help="CN/SAN (implicit rustdesk.carpatica.local)")

    sub.add_parser("init", help="scrie un config.json implicit")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "run"
    dispatch = {
        "run": cmd_run,
        "adduser": cmd_adduser,
        "deluser": cmd_deluser,
        "gentoken": cmd_gentoken,
        "gencert": cmd_gencert,
        "init": cmd_init,
    }
    return dispatch[command](args)
