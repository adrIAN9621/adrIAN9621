"""Linie de comandă: `python -m server [run|adduser|deluser|listusers|gencert]`."""
from __future__ import annotations

import argparse
import datetime
import getpass
import ipaddress
import logging
import os
import sys

from .config import DEFAULT_CONFIG_PATH, Config, load_config, save_config


def _db(cfg: Config):
    from .db import Database
    return Database(cfg.db_file)


def cmd_run(cfg: Config, args) -> int:
    import uvicorn

    from .app import create_app

    if args.host:
        cfg.host = args.host
    if args.port:
        cfg.port = args.port
    ssl_kwargs = {}
    if cfg.tls_available:
        ssl_kwargs = {"ssl_certfile": cfg.cert_file, "ssl_keyfile": cfg.key_file}
        scheme = "https"
    elif cfg.allow_insecure:
        scheme = "http"
        print("ATENȚIE: serverul rulează FĂRĂ TLS (allow_insecure=true). "
              "Folosiți acest mod doar pentru teste!", file=sys.stderr)
    else:
        print(
            "Eroare: nu a fost găsit certificatul TLS.\n"
            f"  certfile: {cfg.cert_file}\n"
            f"  keyfile:  {cfg.key_file}\n\n"
            "Generați un certificat autosemnat cu:\n"
            "    python -m server gencert\n"
            "(din folderul it-asistenta), sau setați căile către un certificat existent în\n"
            f"    {DEFAULT_CONFIG_PATH}\n"
            "Doar pentru teste se poate seta \"allow_insecure\": true în config.json.",
            file=sys.stderr)
        return 2
    users = _db(cfg).list_users()
    if not users:
        print("Notă: nu există niciun tehnician. Adăugați unul cu: "
              "python -m server adduser <nume>", file=sys.stderr)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = create_app(cfg)
    print(f"Carpatica Asistență IT – consola: {scheme}://{cfg.hostname}:{cfg.port}/")
    uvicorn.run(app, host=cfg.host, port=cfg.port, ws_max_size=cfg.max_message_size + 1024,
                proxy_headers=False, server_header=False, log_level="info", **ssl_kwargs)
    return 0


def cmd_adduser(cfg: Config, args) -> int:
    name = args.username.strip()
    if not name or len(name) > 64:
        print("Nume de utilizator invalid.", file=sys.stderr)
        return 1
    display = args.display_name or input(f"Nume afișat [{name}]: ").strip() or name
    while True:
        p1 = getpass.getpass("Parolă: ")
        if len(p1) < 8:
            print("Parola trebuie să aibă cel puțin 8 caractere.")
            continue
        p2 = getpass.getpass("Confirmați parola: ")
        if p1 != p2:
            print("Parolele nu coincid.")
            continue
        break
    _db(cfg).add_user(name, p1, display)
    print(f"Tehnicianul „{name}” ({display}) a fost salvat.")
    return 0


def cmd_deluser(cfg: Config, args) -> int:
    if _db(cfg).delete_user(args.username):
        print(f"Tehnicianul „{args.username}” a fost șters.")
        return 0
    print(f"Tehnicianul „{args.username}” nu există.", file=sys.stderr)
    return 1


def cmd_listusers(cfg: Config, args) -> int:
    for u in _db(cfg).list_users():
        print(f"{u['username']}\t{u['display_name']}")
    return 0


def cmd_gencert(cfg: Config, args) -> int:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    hostname = args.hostname or cfg.hostname
    names = [hostname, "localhost"] + list(args.san or [])
    alt = []
    seen = set()
    for n in names:
        if not n or n in seen:
            continue
        seen.add(n)
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            alt.append(x509.DNSName(n))
    alt.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Carpatica Feroviar – Asistență IT"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=args.days))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                           critical=False)
            .sign(key, hashes.SHA256()))
    os.makedirs(os.path.dirname(cfg.cert_file), exist_ok=True)
    os.makedirs(os.path.dirname(cfg.key_file), exist_ok=True)
    with open(cfg.key_file, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    try:
        os.chmod(cfg.key_file, 0o600)
    except OSError:
        pass
    with open(cfg.cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    fp = cert.fingerprint(hashes.SHA256()).hex(":").upper()
    print(f"Certificat generat pentru {', '.join(sorted(seen))} (valabil {args.days} zile)")
    print(f"  certificat: {cfg.cert_file}\n  cheie:      {cfg.key_file}")
    print(f"  amprentă SHA-256: {fp}")
    print("Distribuiți certificatul (.crt) către agenți/browsere ca autoritate de încredere.")
    if args.hostname and args.hostname != cfg.hostname:
        cfg.hostname = args.hostname
        save_config(cfg, args.config)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m server",
                                description="Carpatica Asistență IT – server")
    p.add_argument("--config", default=None, help="cale config.json")
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="pornește serverul (implicit)")
    r.add_argument("--host")
    r.add_argument("--port", type=int)
    a = sub.add_parser("adduser", help="adaugă/actualizează un tehnician")
    a.add_argument("username")
    a.add_argument("--display-name", "-n", help="numele afișat angajatului")
    d = sub.add_parser("deluser", help="șterge un tehnician")
    d.add_argument("username")
    sub.add_parser("listusers", help="listează tehnicienii")
    g = sub.add_parser("gencert", help="generează un certificat TLS autosemnat")
    g.add_argument("--hostname", help="numele serverului (implicit din config)")
    g.add_argument("--san", action="append", help="nume/IP suplimentar (repetabil)")
    g.add_argument("--days", type=int, default=825)
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    cmd = args.cmd or "run"
    if cmd == "run" and not hasattr(args, "host"):
        args.host = None
        args.port = None
    return {"run": cmd_run, "adduser": cmd_adduser, "deluser": cmd_deluser,
            "listusers": cmd_listusers, "gencert": cmd_gencert}[cmd](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
