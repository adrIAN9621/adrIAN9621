<#
  Intune Remediations - script de DETECȚIE.
  Verifică dacă datele laptopului (ID RustDesk) au fost deja raportate central.
  - Conform (exit 0): există marker-ul de raportare -> nu rulează remedierea.
  - Neconform (exit 1): datele nu au fost încă raportate -> rulează remedierea.

  La STDOUT scrie DOAR ID-ul și hostname-ul (vizibile în portalul Intune).
  Parola NU este scrisă niciodată în portalul Intune.
#>
$DataDir = Join-Path $env:ProgramData "CarpaticaRemote"
$info   = Join-Path $DataDir "device-info.txt"
$marker = Join-Path $DataDir "reported.ok"

if (-not (Test-Path $info)) {
    Write-Output "device-info.txt lipsește (RustDesk neinstalat încă)"
    exit 1
}

$map = @{}
Get-Content $info | ForEach-Object {
    if ($_ -match '^\s*([^=]+)=(.*)$') { $map[$matches[1].Trim()] = $matches[2].Trim() }
}
$id = $map["id"]; $hostn = $map["hostname"]
Write-Output ("ID={0} HOST={1}" -f $id, $hostn)

if (Test-Path $marker) { exit 0 } else { exit 1 }
