@echo off
REM Pornește PDF Studio direct din sursă, cu erorile vizibile pe ecran.
REM Folosește pentru depanare SAU ca mod rapid de a rula aplicatia.
chcp 65001 >nul
cd /d "%~dp0"
title PDF Studio - test

if not exist ".buildvenv\Scripts\activate.bat" (
  echo Pregatesc mediul (o singura data)...
  py -3 -m venv .buildvenv 2>nul || python -m venv .buildvenv
  call .buildvenv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .buildvenv\Scripts\activate.bat
)

echo.
echo === Pornesc PDF Studio din sursa ===
echo (daca apare o eroare, lasa fereastra deschisa si trimite-mi textul)
echo.
python desktop.py
echo.
echo --- aplicatia s-a inchis ---
pause
