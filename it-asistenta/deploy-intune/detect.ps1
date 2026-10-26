# Regula de detectie Intune pentru agentul Carpatica Asistenta IT.
# Exit 0 + text la stdout = INSTALAT; exit 1 = neinstalat.
$exe = Join-Path $env:ProgramFiles "Carpatica Asistenta IT\Carpatica-Asistenta-IT.exe"
if (Test-Path $exe) {
    Write-Output "Installed"
    exit 0
}
exit 1
