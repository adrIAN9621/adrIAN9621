@echo off
REM Construiește PDF-Studio.exe pe Windows. Necesită Python 3.10+.
chcp 65001 >nul
cd /d "%~dp0"
echo === Construire PDF Studio (.exe) ===
py -3 -m venv .buildvenv || python -m venv .buildvenv
call .buildvenv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean pdfstudio.spec
echo.
echo Gata. Executabilul este in:  dist\PDF-Studio.exe
echo (Pentru conversia Word^<-^>PDF e nevoie de LibreOffice instalat pe PC.)
pause
