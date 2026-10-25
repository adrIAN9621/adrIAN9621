<#
  Carpatica Asistență IT – DEZINSTALARE UNIFICATĂ (RustDesk + agent „cu acord").
  Rulează ca SYSTEM (Intune) sau ca administrator.

  Pași:
    a) dezinstalează RustDesk (reutilizează remote-intune\rustdesk\uninstall.ps1);
    b) scoate agentul: oprește procesul, șterge scurtătura din Startup și folderul
       din Program Files.

  Jurnal: C:\ProgramData\CarpaticaRemote\uninstall-unificat.log
#>
[CmdletBinding()]
param(
    [string]$RustDeskDir = (Join-Path $PSScriptRoot "..\rustdesk")
)

$ErrorActionPreference = "SilentlyContinue"
. "$PSScriptRoot\config.ps1"

$DataDir = Join-Path $env:ProgramData "CarpaticaRemote"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$LogFile = Join-Path $DataDir "uninstall-unificat.log"
function Log($m) {
    Add-Content -Path $LogFile -Value ("{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m)
    Write-Output $m
}

Log "=== Dezinstalare UNIFICATĂ Carpatica Asistență IT ==="

# ---------------------------------------------------------------------- RUSTDESK
$rdUninstall = Join-Path $RustDeskDir "uninstall.ps1"
if (Test-Path $rdUninstall) {
    Log "Dezinstalez RustDesk (reutilizez rustdesk\uninstall.ps1)..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $rdUninstall
    Log ("RustDesk uninstall.ps1 a returnat codul {0}." -f $LASTEXITCODE)
} else {
    Log "ATENȚIE: nu găsesc $rdUninstall; sar peste RustDesk."
}

# ------------------------------------------------------------------------- AGENT
Log "Opresc agentul..."
$procName = [System.IO.Path]::GetFileNameWithoutExtension($AGENT_EXE_NAME)
Get-Process -Name $procName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

$startup = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\StartUp"
$lnk = Join-Path $startup ($AGENT_PRODUCT + ".lnk")
if (Test-Path $lnk) { Remove-Item -Force $lnk; Log "Scurtătură Startup ștearsă." }

$agentDir = Join-Path ${env:ProgramFiles} $AGENT_PRODUCT
if (Test-Path $agentDir) { Remove-Item -Recurse -Force $agentDir; Log "Folder agent șters: $agentDir." }

Log "=== Dezinstalare UNIFICATĂ finalizată ==="
exit 0
