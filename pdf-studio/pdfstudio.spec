# PyInstaller spec pentru PDF Studio (un singur .exe).
# Construire pe Windows:  pyinstaller pdfstudio.spec
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("app/static", "app/static")]
binaries = []
hiddenimports = ["uvicorn", "uvicorn.logging", "uvicorn.loops.auto",
                 "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto",
                 "uvicorn.lifespan.on", "app", "app.main", "app.signing",
                 "app.convert", "app.editor", "app.workflow"]

# Pachetele „grele” se adună complet, ca să nu lipsească module la rulare.
for pkg in ("fitz", "pymupdf", "pyhanko", "pyhanko_certvalidator", "asn1crypto",
            "oscrypto", "certvalidator", "pdf2docx", "docx", "cryptography", "PIL",
            "webview", "clr_loader", "pythonnet"):
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
