@echo off
REM Impacheteaza agentul intr-un singur executabil Windows.
REM Necesita Python 3.10+ si PyInstaller: pip install -r requirements.txt pyinstaller
setlocal
cd /d "%~dp0"

if not exist config.json (
  echo [i] config.json nu exista - copiez config.example.json. Editati-l dupa nevoie.
  copy /y config.example.json config.json >nul
)

python -m pip install --upgrade pyinstaller >nul 2>&1

pyinstaller --onefile --noconsole --name "Carpatica-Asistenta-IT" ^
  --icon icon.ico ^
  --add-data "config.json;." ^
  --hidden-import pynput.keyboard._win32 ^
  --hidden-import pynput.mouse._win32 ^
  carpatica_agent.py

REM Agentul citeste config.json de LANGA .exe (nu cel bundle-uit), deci il copiem acolo.
copy /y config.json "dist\config.json" >nul

echo.
echo [OK] Executabil generat in dist\Carpatica-Asistenta-IT.exe
echo     config.json copiat langa .exe in dist\ (editabil).
endlocal
