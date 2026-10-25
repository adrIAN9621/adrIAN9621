<#
  Collect-AutopilotHash.ps1
  Culege "amprenta" hardware (hardware hash) a acestui laptop pentru Windows
  Autopilot si o salveaza intr-un CSV, pe care il incarci in Intune
  (Devices -> Enrollment -> Windows -> Devices -> Import).

  Rulare (PowerShell ca Administrator):
    powershell -ExecutionPolicy Bypass -File .\Collect-AutopilotHash.ps1
  Varianta care incarca DIRECT in Intune (cere login de admin Intune):
    powershell -ExecutionPolicy Bypass -File .\Collect-AutopilotHash.ps1 -Online -GroupTag "Carpatica"
#>
#Requires -RunAsAdministrator
param(
    [string]$OutFile = "$env:USERPROFILE\Desktop\AutopilotHash.csv",
    [switch]$Online,
    [string]$GroupTag = "Carpatica"
)

Set-ExecutionPolicy -Scope Process RemoteSigned -Force

# instaleaza scriptul oficial Microsoft daca lipseste
if (-not (Get-Command Get-WindowsAutopilotInfo.ps1 -ErrorAction SilentlyContinue)) {
    Write-Host "Instalez utilitarul Get-WindowsAutopilotInfo..."
    try { Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force | Out-Null } catch {}
    Install-Script -Name Get-WindowsAutopilotInfo -Force -Scope CurrentUser
    $env:Path += ";$([Environment]::GetFolderPath('MyDocuments'))\WindowsPowerShell\Scripts"
}

$script = (Get-Command Get-WindowsAutopilotInfo.ps1 -ErrorAction SilentlyContinue).Source
if (-not $script) { Write-Error "Nu am putut instala Get-WindowsAutopilotInfo."; exit 1 }

if ($Online) {
    Write-Host "Incarc amprenta DIRECT in Intune (va cere autentificare de admin)..."
    & $script -Online -GroupTag $GroupTag
}
else {
    & $script -OutputFile $OutFile -GroupTag $GroupTag
    Write-Host ""
    Write-Host "GATA. Amprenta salvata in: $OutFile" -ForegroundColor Green
    Write-Host "Incarca acest CSV in Intune: Devices -> Enrollment -> Windows -> Devices -> Import."
}
