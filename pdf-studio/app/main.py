"""PDF Studio – server local (FastAPI) care servește interfața web și API-ul.

Rulează doar pe 127.0.0.1; nimic nu pleacă de pe calculator în afară de
e-mailurile trimise explicit de fluxurile de semnare și cererile către
serviciile de semnare în cloud / marcare temporală configurate de utilizator.
"""
from __future__ import annotations

import base64
import io
import json
import os
import zipfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import convert, editor, signing, workflow

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("PDFSTUDIO_DATA", Path.home() / ".pdf-studio"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

store = workflow.WorkflowStore(str(DATA_DIR / "workflows.db"))
app = FastAPI(title="PDF Studio", docs_url="/api/docs", redoc_url=None)


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _download(data: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


def _stem(name: Optional[str]) -> str:
    return Path(name or "document").stem


async def _read(upload: UploadFile) -> bytes:
    data = await upload.read()
    if not data:
        raise ValueError("Fișierul încărcat este gol.")
    return data


PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ---------------------------------------------------------------- conversie
@app.post("/api/convert/pdf-to-word")
async def pdf_to_word(file: UploadFile = File(...)):
    data = convert.pdf_to_docx(await _read(file))
    return _download(data, _stem(file.filename) + ".docx", DOCX)


@app.post("/api/convert/to-pdf")
async def to_pdf(file: UploadFile = File(...)):
    data = convert.office_to_pdf(await _read(file), file.filename or "document.docx")
    return _download(data, _stem(file.filename) + ".pdf", PDF)


@app.get("/api/convert/status")
def convert_status():
    return {"soffice": convert.find_soffice()}


# ---------------------------------------------------------------- editare
@app.post("/api/pdf/info")
async def pdf_info(file: UploadFile = File(...)):
    return editor.info(await _read(file))


@app.post("/api/pdf/render")
async def pdf_render(file: UploadFile = File(...), page: int = Form(0), zoom: float = Form(1.5)):
    return Response(editor.render_page(await _read(file), page, zoom), media_type="image/png")


@app.post("/api/pdf/edit")
async def pdf_edit(file: UploadFile = File(...), ops: str = Form(...)):
    try:
        ops_list = json.loads(ops)
    except json.JSONDecodeError as exc:
        raise ValueError("Lista de operații este invalidă.") from exc
    data = editor.apply_edits(await _read(file), ops_list)
    return _download(data, _stem(file.filename) + "_editat.pdf", PDF)


@app.post("/api/pdf/merge")
async def pdf_merge(files: list[UploadFile] = File(...)):
    if len(files) < 2:
        raise ValueError("Selectați cel puțin două fișiere PDF.")
    data = editor.merge([await _read(f) for f in files])
    return _download(data, "combinat.pdf", PDF)


@app.post("/api/pdf/split")
async def pdf_split(file: UploadFile = File(...), ranges: str = Form(...)):
    parts = editor.split(await _read(file), ranges)
    buf = io.BytesIO()
    stem = _stem(file.filename)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, part in enumerate(parts, 1):
            zf.writestr(f"{stem}_parte{i}.pdf", part)
    return _download(buf.getvalue(), stem + "_impartit.zip", "application/zip")


@app.post("/api/pdf/compress")
async def pdf_compress(file: UploadFile = File(...)):
    return _download(editor.compress(await _read(file)), _stem(file.filename) + "_comprimat.pdf", PDF)


@app.post("/api/pdf/text")
async def pdf_text(file: UploadFile = File(...)):
    return {"text": editor.extract_text(await _read(file))}


# ---------------------------------------------------------------- semnare
@app.get("/api/sign/pkcs11-libs")
def pkcs11_libs():
    return {"detected": signing.detect_pkcs11_libs(), "known": signing.DEFAULT_PKCS11_LIBS}


@app.post("/api/sign/tokens")
def sign_tokens(lib_path: str = Form(...)):
    return signing.list_pkcs11_tokens(lib_path)


@app.post("/api/sign/token-certs")
def sign_token_certs(lib_path: str = Form(...), token_label: str = Form(...), pin: str = Form(...)):
    return signing.list_token_certs(lib_path, token_label, pin)


async def _sign_params(method: str, form) -> dict:
    if method == "pkcs12":
        pfx = form.get("pfx")
        if pfx is None or not hasattr(pfx, "read"):
            raise ValueError("Selectați fișierul certificatului (.pfx / .p12).")
        return {"pfx": await pfx.read(), "password": form.get("password") or ""}
    if method == "pkcs11":
        return {
            "lib_path": form.get("lib_path") or "",
            "token_label": form.get("token_label") or "",
            "pin": form.get("pin") or "",
            "cert_label": form.get("cert_label") or None,
            "key_id": form.get("key_id") or None,
        }
    if method == "csc":
        return {
            "service_url": form.get("service_url") or "",
            "access_token": form.get("access_token") or "",
            "credential_id": form.get("credential_id") or "",
            "pin": form.get("pin") or None,
            "otp": form.get("otp") or None,
        }
    raise ValueError("Metodă de semnare necunoscută.")


async def _do_sign(request: Request) -> tuple[bytes, str]:
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise ValueError("Selectați documentul PDF.")
    pdf = await upload.read()
    method = form.get("method") or "pkcs12"
    visible = None
    if form.get("visible") in ("1", "true", "on"):
        visible = {k: float(form.get(k) or 0) for k in ("x", "y", "w", "h")}
        visible["page"] = int(form.get("page") or 0)
    signed = signing.sign_pdf(
        pdf,
        method=method,
        params=await _sign_params(method, form),
        field_name=form.get("field_name") or None,
        reason=form.get("reason") or None,
        location=form.get("location") or None,
        contact=form.get("contact") or None,
        visible=visible,
        timestamp_url=form.get("timestamp_url") or None,
    )
    return signed, upload.filename or "document.pdf"


@app.post("/api/sign")
async def sign(request: Request):
    signed, name = await _do_sign(request)
    return _download(signed, _stem(name) + "_semnat.pdf", PDF)


@app.post("/api/validate")
async def validate(file: UploadFile = File(...), roots: list[UploadFile] = File(default=[])):
    extra = [await r.read() for r in roots if r.filename]
    return signing.validate_pdf(await _read(file), extra or None)


@app.post("/api/sign/test-certificate")
def test_certificate(name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    data = signing.make_test_pfx(name, email, password)
    return _download(data, "certificat_test.pfx", "application/x-pkcs12")


# ---------------------------------------------------------------- fluxuri
@app.get("/api/settings")
def get_settings():
    s = dict(store.get_settings())
    for k in ("smtp_password", "imap_password"):
        if s.get(k):
            s[k] = "********"
    return s


@app.post("/api/settings")
async def save_settings(request: Request):
    data = await request.json()
    current = store.get_settings()
    for k in ("smtp_password", "imap_password"):
        if data.get(k) == "********":
            data[k] = current.get(k, "")
    store.save_settings(data)
    return {"ok": True}


@app.post("/api/settings/test-smtp")
def test_smtp():
    return store.test_smtp()


@app.post("/api/settings/test-imap")
def test_imap():
    return store.test_imap()


@app.get("/api/workflows")
def wf_list():
    return store.list()


@app.post("/api/workflows")
async def wf_create(
    file: UploadFile = File(...),
    name: str = Form(...),
    signers: str = Form(...),
    message: str = Form(""),
    start: bool = Form(False),
):
    signer_list = json.loads(signers)
    if not signer_list:
        raise ValueError("Adăugați cel puțin un semnatar.")
    wf_id = store.create(name, await _read(file), file.filename or "document.pdf", signer_list, message)
    if start:
        store.start(wf_id)
    return store.get(wf_id)


@app.get("/api/workflows/{wf_id}")
def wf_get(wf_id: int):
    return store.get(wf_id)


@app.get("/api/workflows/{wf_id}/document")
def wf_document(wf_id: int):
    filename, data = store.get_document(wf_id)
    return _download(data, filename, PDF)


@app.post("/api/workflows/{wf_id}/start")
def wf_start(wf_id: int):
    store.start(wf_id)
    return store.get(wf_id)


@app.post("/api/workflows/{wf_id}/submit")
async def wf_submit(wf_id: int, file: UploadFile = File(...)):
    report = store.submit_signed(wf_id, await _read(file), source="manual")
    return {"report": report, "workflow": store.get(wf_id)}


@app.post("/api/workflows/{wf_id}/sign-local")
async def wf_sign_local(wf_id: int, request: Request):
    """Semnează pasul curent direct din aplicație (inițiatorul este semnatarul curent)."""
    form = await request.form()
    _, pdf = store.get_document(wf_id)
    method = form.get("method") or "pkcs12"
    visible = None
    if form.get("visible") in ("1", "true", "on"):
        visible = {k: float(form.get(k) or 0) for k in ("x", "y", "w", "h")}
        visible["page"] = int(form.get("page") or 0)
    signed = signing.sign_pdf(
        pdf,
        method=method,
        params=await _sign_params(method, form),
        reason=form.get("reason") or None,
        location=form.get("location") or None,
        visible=visible,
        timestamp_url=form.get("timestamp_url") or None,
    )
    report = store.sign_current_step_locally(wf_id, signed)
    return {"report": report, "workflow": store.get(wf_id)}


@app.post("/api/workflows/{wf_id}/remind")
def wf_remind(wf_id: int):
    store.remind(wf_id)
    return store.get(wf_id)


@app.post("/api/workflows/{wf_id}/cancel")
def wf_cancel(wf_id: int):
    store.cancel(wf_id)
    return store.get(wf_id)


@app.post("/api/workflows/check-inbox")
def wf_check_inbox():
    return store.check_inbox()


# ---------------------------------------------------------------- UI
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")
