<#
  Intune Remediations - script de REMEDIERE.
  Trimite datele laptopului (ID + parola + hostname) către colectorul intern,
  peste HTTPS, și scrie marker-ul de raportare la succes.

  Editați $REPORT_URL și $REPORT_TOKEN ca să corespundă colectorului vostru
  (vezi folderul ../collector). Parola merge DOAR către acest endpoint intern,
  nu în portalul Intune.
#>
$REPORT_URL   = "https://rustdesk.carpatica.local:8070/api/register"
$REPORT_TOKEN = "SCHIMBATI_ACEST_TOKEN"   # același cu $COLLECTOR_TOKEN din colector

$DataDir = Join-Path $env:ProgramData "CarpaticaRemote"
$info   = Join-Path $DataDir "device-info.txt"
$marker = Join-Path $DataDir "reported.ok"
$log    = Join-Path $DataDir "remediation.log"
function Log($m){ Add-Content $log ("{0}  {1}" -f (Get-Date -Format s), $m) }

if (-not (Test-Path $info)) { Log "device-info.txt lipsește"; exit 1 }

$map = @{}
Get-Content $info | ForEach-Object {
    if ($_ -match '^\s*([^=]+)=(.*)$') { $map[$matches[1].Trim()] = $matches[2].Trim() }
}
$body = @{
    id       = $map["id"]
    password = $map["password"]
    hostname = $map["hostname"]
    server   = $map["server"]
    user     = (try { (Get-CimInstance Win32_ComputerSystem).UserName } catch { "" })
    reported = (Get-Date -Format s)
} | ConvertTo-Json

try {
    Invoke-RestMethod -Uri $REPORT_URL -Method Post -ContentType "application/json" `
        -Headers @{ "Authorization" = "Bearer $REPORT_TOKEN" } -Body $body -TimeoutSec 25 | Out-Null
    New-Item -ItemType File -Force -Path $marker | Out-Null
    Log ("Raportat ID {0}" -f $map["id"])
    Write-Output ("Raportat ID {0}" -f $map["id"])
    exit 0
} catch {
    Log ("Raportare eșuată: " + $_.Exception.Message)
    Write-Output ("Raportare eșuată: " + $_.Exception.Message)
    exit 1
}
