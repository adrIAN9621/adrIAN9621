<#
  Intune Remediations – REMEDIERE (pachet unificat RustDesk + agent).
  Rulează când DETECȚIA a găsit o problemă. Face, în ordine:
    1. pornește serviciul RustDesk dacă e oprit;
    2. re-raportează ID-ul + parola RustDesk la serverul unificat
       (POST /api/register cu „Authorization: Bearer <ingest_token>");
       adaptat din remote-intune\rustdesk\remediation\Remediate-ReportDeviceInfo.ps1;
    3. verifică prezența agentului + a scurtăturii din Startup și semnalează
       dacă lipsesc (reinstalarea completă se face cu aplicația Win32).

  Parola merge DOAR către endpoint-ul intern /api/register, nu în portalul Intune.

  Jurnal: C:\ProgramData\CarpaticaRemote\remediation-unificat.log
#>

# ----- Trebuie să corespundă cu config.ps1 din pachetul unificat -----
# Obțineți tokenul cu `python -m server token` pe serverul unificat.
$REGISTER_URL   = "https://server.carpatica:8443/api/register"
$INGEST_TOKEN   = "SCHIMBATI_ACEST_TOKEN"
$AGENT_PRODUCT  = "Carpatica Asistenta IT"
$AGENT_EXE_NAME = "Carpatica-Asistenta-IT.exe"
# ---------------------------------------------------------------------

$DataDir = Join-Path $env:ProgramData "CarpaticaRemote"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$info = Join-Path $DataDir "device-info.txt"
$log  = Join-Path $DataDir "remediation-unificat.log"
function Log($m) {
    Add-Content -Path $log -Value ("{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m)
    Write-Output $m
}

$ok = $true

# 1) Serviciul RustDesk
$svc = Get-Service -Name "RustDesk" -ErrorAction SilentlyContinue
if ($svc) {
    if ($svc.Status -ne "Running") {
        Log "Pornesc serviciul RustDesk..."
        Set-Service -Name "RustDesk" -StartupType Automatic -ErrorAction SilentlyContinue
        Start-Service -Name "RustDesk" -ErrorAction SilentlyContinue
    }
} else {
    Log "Serviciul RustDesk lipsește - necesită reinstalarea aplicației Win32."
    $ok = $false
}

# 2) Re-raportare la serverul unificat
if (Test-Path $info) {
    $map = @{}
    Get-Content $info | ForEach-Object {
        if ($_ -match '^\s*([^=]+)=(.*)$') { $map[$matches[1].Trim()] = $matches[2].Trim() }
    }
    if ($INGEST_TOKEN -and $INGEST_TOKEN -ne "SCHIMBATI_ACEST_TOKEN") {
        $user = ""
        try { $user = (Get-CimInstance Win32_ComputerSystem).UserName } catch { $user = "" }
        $body = @{
            id       = $map["id"]
            password = $map["password"]
            hostname = $map["hostname"]
            server   = $map["server"]
            user     = $user
        } | ConvertTo-Json
        try {
            Invoke-RestMethod -Uri $REGISTER_URL -Method Post -ContentType "application/json" `
                -Headers @{ "Authorization" = "Bearer $INGEST_TOKEN" } -Body $body -TimeoutSec 25 | Out-Null
            Log ("Re-raportat ID {0} la {1}." -f $map["id"], $REGISTER_URL)
        } catch {
            Log ("Re-raportare eșuată: " + $_.Exception.Message)
            $ok = $false
        }
    } else {
        Log "INGEST_TOKEN nu este setat - sar peste raportare."
        $ok = $false
    }
} else {
    Log "device-info.txt lipsește - RustDesk nu e configurat; necesită reinstalare Win32."
    $ok = $false
}

# 3) Prezența agentului
$agentExe = Join-Path (Join-Path ${env:ProgramFiles} $AGENT_PRODUCT) $AGENT_EXE_NAME
$startup  = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\StartUp"
$lnk      = Join-Path $startup ($AGENT_PRODUCT + ".lnk")
if (-not (Test-Path $agentExe)) { Log "Agentul lipsește din Program Files - necesită reinstalarea aplicației Win32."; $ok = $false }
elseif (-not (Test-Path $lnk))  { Log "Scurtătura din Startup lipsește - necesită reinstalarea aplicației Win32."; $ok = $false }

if ($ok) { Log "Remediere OK."; exit 0 } else { Log "Remediere parțială - vedeți jurnalul."; exit 1 }
