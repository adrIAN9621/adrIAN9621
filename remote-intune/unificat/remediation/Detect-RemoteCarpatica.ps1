<#
  Intune Remediations – DETECȚIE (pachet unificat RustDesk + agent).
  Verifică periodic că AMBELE componente sunt prezente și active:
    - RustDesk: executabil în Program Files + serviciul „RustDesk" pornit + device-info.txt
    - Agent „cu acord": executabil în Program Files + scurtătură în Startup

  Conform     (exit 0) = ambele OK -> NU rulează remedierea.
  Neconform   (exit 1) = ceva lipsește/oprit -> rulează remedierea.

  La STDOUT scrie DOAR ID-ul RustDesk și hostname-ul (vizibile în portalul Intune).
  Parola NU apare niciodată în portalul Intune.
#>

# ----- Trebuie să corespundă cu config.ps1 din pachetul unificat -----
$AGENT_PRODUCT  = "Carpatica Asistenta IT"
$AGENT_EXE_NAME = "Carpatica-Asistenta-IT.exe"
# ---------------------------------------------------------------------

$problems = @()

# RustDesk
$rdExe = Join-Path ${env:ProgramFiles} "RustDesk\rustdesk.exe"
if (-not (Test-Path $rdExe)) { $problems += "RustDesk lipsește" }
$svc = Get-Service -Name "RustDesk" -ErrorAction SilentlyContinue
if (-not $svc -or $svc.Status -ne "Running") { $problems += "serviciu RustDesk oprit" }

$DataDir = Join-Path $env:ProgramData "CarpaticaRemote"
$info = Join-Path $DataDir "device-info.txt"
if (-not (Test-Path $info)) { $problems += "device-info.txt lipsește" }

# Agent „cu acord"
$agentExe = Join-Path (Join-Path ${env:ProgramFiles} $AGENT_PRODUCT) $AGENT_EXE_NAME
if (-not (Test-Path $agentExe)) { $problems += "agent lipsește" }
$startup = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\StartUp"
$lnk = Join-Path $startup ($AGENT_PRODUCT + ".lnk")
if (-not (Test-Path $lnk)) { $problems += "scurtătură Startup lipsește" }

# ID + hostname pentru vizibilitate în portal (fără parolă)
$id = ""; $hostn = $env:COMPUTERNAME
if (Test-Path $info) {
    Get-Content $info | ForEach-Object {
        if ($_ -match '^\s*id\s*=\s*(.+)$')       { $id = $matches[1].Trim() }
        if ($_ -match '^\s*hostname\s*=\s*(.+)$')  { $hostn = $matches[1].Trim() }
    }
}

if ($problems.Count -eq 0) {
    Write-Output ("OK ID={0} HOST={1}" -f $id, $hostn)
    exit 0
} else {
    Write-Output ("NECONFORM ({0}) ID={1} HOST={2}" -f ($problems -join ", "), $id, $hostn)
    exit 1
}
