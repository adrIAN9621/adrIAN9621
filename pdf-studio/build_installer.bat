@echo off
REM ============================================================
REM  Construiește INSTALATORUL PDF Studio (PDF-Studio-Setup.exe)
REM  Rulează o singură dată, pe un PC cu Windows + Python.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === Pasul 1/2: construire aplicatie (.exe) ===
py -3 -m venv .buildvenv || python -m venv .buildvenv
call .buildvenv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean pdfstudio.spec
if not exist "dist\PDF-Studio.exe" (
  echo EROARE: nu s-a creat dist\PDF-Studio.exe
  pause & exit /b 1
)

echo.
echo === Pasul 2/2: impachetare in instalator ===
set "ISCC="
for %%P in (
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
  "%ProgramFiles%\Inno Setup 6\ISCC.exe"
) do if exist "%%~P" set "ISCC=%%~P"

if "%ISCC%"=="" (
  echo.
  echo Inno Setup nu este instalat. E gratuit si se instaleaza o singura data:
  echo   https://jrsoftware.org/isdl.php   ^(descarca "innosetup-6.x.x.exe" si instaleaza-l^)
  echo Dupa instalare, ruleaza din nou acest fisier.
  echo.
  echo Deocamdata ai macar aplicatia simpla in:  dist\PDF-Studio.exe
  pause & exit /b 1
)

"%ISCC%" "installer\pdfstudio.iss"
echo.
echo ============================================================
echo  GATA. Instalatorul este in:  installer\Output\PDF-Studio-Setup.exe
echo  Il copiezi pe orice laptop, dublu-clic, Next-Next, si gata.
echo  Pune si scurtatura pe desktop automat.
echo ============================================================
pause
