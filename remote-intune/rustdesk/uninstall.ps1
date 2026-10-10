<#  Carpatica Feroviar - dezinstalare RustDesk. Rulează ca SYSTEM sau admin. #>
$ErrorActionPreference = "SilentlyContinue"
$DataDir = Join-Path $env:ProgramData "CarpaticaRemote"
$log = Join-Path $DataDir "uninstall.log"
function Log($m){ Add-Content $log ("{0}  {1}" -f (Get-Date -Format s), $m); Write-Output $m }
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

$exe = Join-Path ${env:ProgramFiles} "RustDesk\rustdesk.exe"
try {
  if (Test-Path $exe) {
    Log "Opresc și dezinstalez serviciul..."
    Start-Process -FilePath $exe -ArgumentList "--uninstall-service" -Wait
    Start-Sleep 5
    Log "Rulez dezinstalarea aplicației..."
    Start-Process -FilePath $exe -ArgumentList "--uninstall" -Wait
  }
  Get-Service -Name "RustDesk" -ErrorAction SilentlyContinue | Stop-Service -Force -ErrorAction SilentlyContinue
  sc.exe delete RustDesk | Out-Null
  Remove-Item -Recurse -Force (Join-Path ${env:ProgramFiles} "RustDesk") -ErrorAction SilentlyContinue
  Log "Dezinstalare finalizată."
  exit 0
} catch { Log ("EROARE: " + $_.Exception.Message); exit 1 }
