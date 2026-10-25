<#
  Carpatica Asistență IT – INSTALATOR UNIC (RustDesk + agent „cu acord").

  Rulează ca SYSTEM (Intune) sau ca administrator (manual). Într-o singură rulare:
    a) instalează/configurează RustDesk ca serviciu nesupravegheat
       (reutilizează, NEMODIFICAT, remote-intune\rustdesk\install.ps1);
    b) scoate ID-ul + parola RustDesk și le RAPORTEAZĂ la serverul unificat prin
       POST /api/register cu „Authorization: Bearer <ingest_token>" (raportarea
       e făcută chiar de install.ps1, configurat să țintească /api/register);
    c) instalează agentul „cu acord": copiază Carpatica-Asistenta-IT.exe în
       Program Files, scrie config.json (server_url = ws(s)://.../ws/agent) și
       pune o scurtătură în Startup (toți utilizatorii).

  Jurnal: C:\ProgramData\CarpaticaRemote\install-unificat.log

  Parametri opționali:
    -RustDeskDir <cale>   folderul cu scripturile RustDesk (implicit ..\rustdesk)
    -SkipRustDesk         sare peste pasul RustDesk
    -SkipAgent            sare peste pasul agentului
#>
[CmdletBinding()]
param(
    [string]$RustDeskDir = (Join-Path $PSScriptRoot "..\rustdesk"),
    [switch]$SkipRustDesk,
    [switch]$SkipAgent
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\config.ps1"

$DataDir = Join-Path $env:ProgramData "CarpaticaRemote"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$LogFile = Join-Path $DataDir "install-unificat.log"

function Log($m) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m
    Add-Content -Path $LogFile -Value $line
    Write-Output $line
}

# Emite o valoare PowerShell ca literal single-quote (sigur pentru chei/URL-uri).
function PsLit($v) {
    if ($null -eq $v) { return '$null' }
    if ($v -is [bool]) { if ($v) { return '$true' } else { return '$false' } }
    if ($v -is [int])  { return [string]$v }
    return "'" + ([string]$v).Replace("'", "''") + "'"
}

try {
    Log "=== Instalare UNIFICATĂ Carpatica Asistență IT ==="
    Log ("Context: {0}" -f (([Security.Principal.WindowsIdentity]::GetCurrent()).Name))
    Log ("Server unificat: {0}" -f $SERVER_URL)

    # --------------------------------------------------------------------- RUSTDESK
    if (-not $SkipRustDesk) {
        $rdInstall = Join-Path $RustDeskDir "install.ps1"
        if (-not (Test-Path $rdInstall)) {
            throw "Nu găsesc scriptul RustDesk: $rdInstall (folosiți -RustDeskDir)."
        }
        if (-not $INGEST_TOKEN -or $INGEST_TOKEN -eq "SCHIMBATI_ACEST_TOKEN") {
            Log "ATENȚIE: INGEST_TOKEN nu este setat în config.ps1 - raportarea la /api/register va fi respinsă (401)."
        }

        # Stagiere: copiem install.ps1 (+ rustdesk.exe dacă există) într-un folder
        # temporar și generăm acolo config.ps1 din valorile UNIFICATE, astfel încât
        # install.ps1 (care face `. "$PSScriptRoot\config.ps1"`) să raporteze la
        # /api/register al serverului unificat. NU modificăm scripturile originale.
        $stage = Join-Path $env:TEMP ("CarpaticaRDStage_" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Force -Path $stage | Out-Null
        try {
            Copy-Item -Path $rdInstall -Destination (Join-Path $stage "install.ps1") -Force
            foreach ($bundle in @("rustdesk.exe")) {
                $src = Join-Path $PSScriptRoot $bundle
                if (-not (Test-Path $src)) { $src = Join-Path $RustDeskDir $bundle }
                if (Test-Path $src) {
                    Copy-Item -Path $src -Destination (Join-Path $stage $bundle) -Force
                    Log ("Folosesc {0} bundelat." -f $bundle)
                }
            }

            $cfgLines = @(
                "# Config generat automat de Install-RemoteCarpatica.ps1 - NU editați manual.",
                "`$RD_HOST = $(PsLit $RD_HOST)",
                "`$RD_KEY = $(PsLit $RD_KEY)",
                "`$RD_RELAY = $(PsLit $RD_RELAY)",
                "`$RD_API = $(PsLit $RD_API)",
                "`$RD_PASSWORD = $(PsLit $RD_PASSWORD)",
                "`$RD_RANDOM_LEN = $(PsLit $RD_RANDOM_LEN)",
                "`$RD_APPROVE_MODE = $(PsLit $RD_APPROVE_MODE)",
                "`$RD_INSTALL_SERVICE = $(PsLit $RD_INSTALL_SERVICE)",
                "`$RD_FALLBACK_DOWNLOAD = $(PsLit $RD_FALLBACK_DOWNLOAD)",
                "`$RD_PRODUCT = $(PsLit $RD_PRODUCT)",
                "# Raportare către serverul unificat (POST /api/register + Bearer ingest_token):",
                "`$RD_REPORT_URL = $(PsLit $REGISTER_URL)",
                "`$RD_REPORT_TOKEN = $(PsLit $INGEST_TOKEN)"
            )
            Set-Content -Path (Join-Path $stage "config.ps1") -Value $cfgLines -Encoding UTF8

            Log "Rulez instalarea RustDesk (reutilizez rustdesk\install.ps1)..."
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $stage "install.ps1")
            $rc = $LASTEXITCODE
            Log ("RustDesk install.ps1 a returnat codul {0}." -f $rc)
            if ($rc -ne 0) { throw "Instalarea RustDesk a eșuat (cod $rc). Vedeți install.log." }
        }
        finally {
            Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
        }
    } else {
        Log "Pasul RustDesk a fost sărit (-SkipRustDesk)."
    }

    # ----------------------------------------------------------------------- AGENT
    if (-not $SkipAgent) {
        $agentSrc = Join-Path $PSScriptRoot $AGENT_EXE_NAME
        if (-not (Test-Path $agentSrc)) {
            Log ("EROARE: {0} nu există lângă acest script." -f $AGENT_EXE_NAME)
            Log "Construiți-l întâi: rulați it-asistenta\agent\build_exe.bat (Windows, Python 3.10+),"
            Log ("apoi copiați dist\{0} lângă Install-RemoteCarpatica.ps1." -f $AGENT_EXE_NAME)
            throw "Executabilul agentului lipsește: $agentSrc"
        }

        $agentDir = Join-Path ${env:ProgramFiles} $AGENT_PRODUCT
        New-Item -ItemType Directory -Force -Path $agentDir | Out-Null
        $agentDst = Join-Path $agentDir $AGENT_EXE_NAME
        Copy-Item -Path $agentSrc -Destination $agentDst -Force
        Log ("Agent copiat în {0}." -f $agentDst)

        # config.json lângă executabil (agentul îl citește primul din app_base_dir).
        $cfg = [ordered]@{
            server_url      = $AGENT_WS_URL
            ca_file         = $(if ($AGENT_CA_FILE) { $AGENT_CA_FILE } else { $null })
            verify_tls      = [bool]$AGENT_VERIFY_TLS
            allow_insecure  = $false
            default_quality = 60
            default_scale   = 1.0
            default_fps     = 10
        }
        $cfgJson = $cfg | ConvertTo-Json
        Set-Content -Path (Join-Path $agentDir "config.json") -Value $cfgJson -Encoding UTF8
        Log ("Agent config.json scris (server_url = {0})." -f $AGENT_WS_URL)

        # Scurtătură în Startup pentru toți utilizatorii (pornește la logon).
        $startup = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\StartUp"
        New-Item -ItemType Directory -Force -Path $startup | Out-Null
        $lnk = Join-Path $startup ($AGENT_PRODUCT + ".lnk")
        $ws = New-Object -ComObject WScript.Shell
        $sc = $ws.CreateShortcut($lnk)
        $sc.TargetPath = $agentDst
        $sc.WorkingDirectory = $agentDir
        $sc.Description = "Carpatica Asistență IT (agent cu acord)"
        $sc.Save()
        Log ("Scurtătură Startup creată: {0}." -f $lnk)
    } else {
        Log "Pasul agentului a fost sărit (-SkipAgent)."
    }

    Log "=== Instalare UNIFICATĂ finalizată cu succes ==="
    exit 0
}
catch {
    Log ("EROARE: {0}" -f $_.Exception.Message)
    Log ($_.ScriptStackTrace)
    exit 1
}
