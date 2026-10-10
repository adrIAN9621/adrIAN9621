"""Conversii de documente: PDF -> Word și Office -> PDF."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

OFFICE_EXTENSIONS = {
    ".docx", ".doc", ".odt", ".rtf", ".txt",
    ".xlsx", ".xls", ".ods", ".csv",
    ".pptx", ".ppt", ".odp",
}

SOFFICE_TIMEOUT = 180


def pdf_to_docx(pdf: bytes) -> bytes:
    """Convertește un PDF în DOCX folosind pdf2docx."""
    if not pdf:
        raise ValueError("Fișierul PDF este gol.")
    try:
        from pdf2docx import Converter
    except ImportError as exc:  # pragma: no cover
        raise ValueError("Biblioteca pdf2docx nu este instalată.") from exc

    tmp = tempfile.mkdtemp(prefix="pdfstudio_p2d_")
    try:
        src = os.path.join(tmp, "input.pdf")
        dst = os.path.join(tmp, "output.docx")
        with open(src, "wb") as f:
            f.write(pdf)
        try:
            cv = Converter(src)
            try:
                cv.convert(dst)
            finally:
                cv.close()
        except Exception as exc:
            raise ValueError(f"Conversia PDF în Word a eșuat: {exc}") from exc
        if not os.path.exists(dst) or os.path.getsize(dst) == 0:
            raise ValueError("Conversia PDF în Word nu a produs niciun fișier.")
        with open(dst, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def find_soffice() -> str | None:
    """Caută executabilul LibreOffice (soffice) în PATH și în locațiile uzuale."""
    for name in ("soffice", "soffice.exe", "libreoffice", "soffice.com"):
        p = shutil.which(name)
        if p:
            return p
    candidates: list[str] = []
    if sys.platform.startswith("win"):
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(env)
            if base:
                candidates.append(os.path.join(base, "LibreOffice", "program", "soffice.exe"))
        candidates += [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
    elif sys.platform == "darwin":
        candidates += [
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            os.path.expanduser("~/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        ]
    else:
        candidates += [
            "/usr/bin/soffice",
            "/usr/local/bin/soffice",
            "/usr/lib/libreoffice/program/soffice",
            "/opt/libreoffice/program/soffice",
            "/snap/bin/libreoffice",
        ]
        candidates += [str(p) for p in sorted(Path("/opt").glob("libreoffice*/program/soffice"))]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def _safe_name(filename: str) -> tuple[str, str]:
    base = os.path.basename(filename or "document")
    stem, ext = os.path.splitext(base)
    ext = ext.lower()
    stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem) or "document"
    return stem, ext


def _convert_with_soffice(soffice: str, data: bytes, stem: str, ext: str) -> bytes:
    tmp = tempfile.mkdtemp(prefix="pdfstudio_o2p_")
    try:
        src = os.path.join(tmp, stem + ext)
        outdir = os.path.join(tmp, "out")
        profile = os.path.join(tmp, "profile")
        os.makedirs(outdir)
        os.makedirs(profile)
        with open(src, "wb") as f:
            f.write(data)
        cmd = [
            soffice,
            f"-env:UserInstallation={Path(profile).as_uri()}",
            "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nologo",
            "--convert-to", "pdf",
            "--outdir", outdir,
            src,
        ]
        kwargs = {}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=SOFFICE_TIMEOUT, **kwargs,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Conversia cu LibreOffice a depășit timpul limită (180 s).") from exc
        except OSError as exc:
            raise ValueError(f"LibreOffice nu a putut fi pornit: {exc}") from exc
        out = os.path.join(outdir, stem + ".pdf")
        if not os.path.exists(out):
            pdfs = list(Path(outdir).glob("*.pdf"))
            out = str(pdfs[0]) if pdfs else ""
        if not out or os.path.getsize(out) == 0:
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()
            raise ValueError(
                "Conversia cu LibreOffice a eșuat" + (f": {err}" if err else ".")
            )
        with open(out, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _convert_with_word(data: bytes, stem: str, ext: str) -> bytes:
    from docx2pdf import convert  # type: ignore

    tmp = tempfile.mkdtemp(prefix="pdfstudio_w2p_")
    try:
        src = os.path.join(tmp, stem + ext)
        dst = os.path.join(tmp, stem + ".pdf")
        with open(src, "wb") as f:
            f.write(data)
        try:
            convert(src, dst)
        except Exception as exc:
            raise ValueError(f"Conversia cu Microsoft Word a eșuat: {exc}") from exc
        if not os.path.exists(dst) or os.path.getsize(dst) == 0:
            raise ValueError("Conversia cu Microsoft Word nu a produs niciun fișier.")
        with open(dst, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def office_to_pdf(data: bytes, filename: str) -> bytes:
    """Convertește un document Office (docx/doc/odt/rtf/xlsx/pptx/txt...) în PDF."""
    if not data:
        raise ValueError("Fișierul încărcat este gol.")
    stem, ext = _safe_name(filename)
    if ext == ".pdf":
        return data
    if ext not in OFFICE_EXTENSIONS:
        raise ValueError(
            f"Tip de fișier neacceptat pentru conversie: „{ext or filename}”. "
            "Sunt acceptate: " + ", ".join(sorted(OFFICE_EXTENSIONS)) + "."
        )

    soffice = find_soffice()
    if soffice:
        return _convert_with_soffice(soffice, data, stem, ext)

    if sys.platform.startswith("win") and ext in (".docx", ".doc"):
        try:
            import docx2pdf  # noqa: F401
        except ImportError:
            pass
        else:
            return _convert_with_word(data, stem, ext)

    raise ValueError(
        "Nu a fost găsit LibreOffice pe acest calculator. Instalați LibreOffice "
        "(https://www.libreoffice.org/download/) pentru conversia documentelor în PDF"
        + (
            " sau instalați Microsoft Word și pachetul Python „docx2pdf” (doar pentru .docx/.doc)."
            if sys.platform.startswith("win") else "."
        )
    )
