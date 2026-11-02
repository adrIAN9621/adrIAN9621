@echo off
REM Construieste launcher-ul desktop al consolei (fereastra proprie, fara browser vizibil).
REM Necesita Python 3.10+ si PyInstaller.
setlocal
cd /d "%~dp0"

python -m pip install --upgrade pyinstaller >nul 2>&1

pyinstaller --onefile --noconsole --name "Carpatica-Consola-IT" ^
  --icon "..\agent\icon.ico" ^
  consola_desktop.py

REM Launcher-ul citeste config.json de LANGA .exe (console_url). Il copiem acolo.
copy /y config.json "dist\config.json" >nul

echo.
echo [OK] Executabil generat in dist\Carpatica-Consola-IT.exe
echo     config.json copiat langa .exe (console_url, editabil).
endlocal
