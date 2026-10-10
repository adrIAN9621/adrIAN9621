# PyInstaller spec pentru PDF Studio (un singur .exe).
# Construire pe Windows:  pyinstaller pdfstudio.spec
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("app/static", "app/static")]
binaries = []
hiddenimports = ["uvicorn", "uvicorn.logging", "uvicorn.loops.auto",
                 "uvicorn.loops.asyncio",
                 "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
                 "uvicorn.protocols.websockets.auto",
                 "uvicorn.protocols.websockets.websockets_impl",
                 "uvicorn.protocols.websockets.wsproto_impl",
                 "uvicorn.lifespan.on", "uvicorn.lifespan.off",
                 "anyio", "anyio._backends", "anyio._backends._asyncio",
                 "app", "app.main", "app.signing",
                 "app.convert", "app.editor", "app.workflow", "app.winsign"]
for _p in ("fastapi", "starlette", "uvicorn", "anyio", "multipart", "websockets"):
    try:
        hiddenimports += collect_submodules(_p)
    except Exception:
        pass

# Pachetele „grele” se adună complet, ca să nu lipsească module la rulare.
for pkg in ("fitz", "pymupdf", "pyhanko", "pyhanko_certvalidator", "asn1crypto",
            "oscrypto", "certvalidator", "pdf2docx", "docx", "cryptography", "PIL",
            ):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

block_cipher = None

a = Analysis(["desktop.py"], pathex=["."], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
             excludes=["tkinter", "matplotlib", "pytest"], cipher=block_cipher)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
          name="PDF-Studio", debug=False, strip=False, upx=False,
          console=False, icon="app/static/brand/icon.ico")
