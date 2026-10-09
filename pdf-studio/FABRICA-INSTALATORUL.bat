@echo off
REM ====================================================================
REM  UN SINGUR DUBLU-CLIC: fabrică PDF-Studio-Setup.exe
REM  Isi instaleaza singur Python si Inno Setup (prin winget), apoi
REM  construieste instalatorul. Ruleaza pe Windows 10/11.
REM ====================================================================
chcp 65001 >nul
cd /d "%~dp0"
title Fabrica instalatorul PDF Studio

echo.
echo Acest fisier instaleaza automat ce trebuie si creeaza instalatorul.
echo Poate dura 5-10 minute la prima rulare. Nu inchideti fereastra.
echo.

REM --- 1. Python ---
where py >nul 2>&1 || where python >nul 2>&1
if errorlevel 1 (
  echo [1/4] Instalez Python...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --silent
  REM reimprospatam PATH-ul in sesiunea curenta
  set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts"
) else (
  echo [1/4] Python este deja instalat.
)

REM --- 2. Inno Setup ---
set "ISCC="
for %%P in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do if exist "%%~P" set "ISCC=%%~P"
if "%ISCC%"=="" (
  echo [2/4] Instalez Inno Setup...
  winget install -e --id JRSoftware.InnoSetup --accept-source-agreements --accept-package-agreements --silent
  for %%P in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do if exist "%%~P" set "ISCC=%%~P"
) else (
  echo [2/4] Inno Setup este deja instalat.
)

REM --- 3. Construire aplicatie (.exe) ---
echo [3/4] Construiesc aplicatia...
py -3 -m venv .buildvenv 2>nul || python -m venv .buildvenv
call .buildvenv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean pdfstudio.spec
if not exist "dist\PDF-Studio.exe" (
  echo EROARE la construirea aplicatiei. Trimiteti acest mesaj mai departe.
  pause & exit /b 1
)

REM --- 4. Impachetare in instalator ---
echo [4/4] Creez instalatorul...
if "%ISCC%"=="" for %%P in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do if exist "%%~P" set "ISCC=%%~P"
if "%ISCC%"=="" (
  echo Nu am gasit Inno Setup. Deschideti din nou acest fisier dupa ce se termina instalarea lui.
  pause & exit /b 1
)
"%ISCC%" "installer\pdfstudio.iss"

echo.
echo =====================================================================
echo  GATA! Instalatorul este:
echo     %cd%\installer\Output\PDF-Studio-Setup.exe
echo.
echo  Copiati acel fisier pe orice laptop, dublu-clic, Next-Next,
echo  si apare scurtatura pe desktop ca la orice program.
echo =====================================================================
explorer "%cd%\installer\Output"
pause
