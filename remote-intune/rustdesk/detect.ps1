<#  Intune - script de detecție. Iese cu 0 + output DACĂ aplicația e prezentă. #>
$exe = Join-Path ${env:ProgramFiles} "RustDesk\rustdesk.exe"
$svc = Get-Service -Name "RustDesk" -ErrorAction SilentlyContinue
$info = Join-Path $env:ProgramData "CarpaticaRemote\device-info.txt"
if ((Test-Path $exe) -and $svc -and (Test-Path $info)) {
    Write-Output "Carpatica Remote prezent"
    exit 0
}
exit 1
