<#
  Carpatica Feroviar - configurare client RustDesk pe PC-ul tehnicianului.
  Setează automat serverul companiei (gazda + cheia), ca tehnicianul să nu le
  introducă manual. Rulați ca administrator pe stația tehnicianului.

  Nu instalează serviciu și nu setează acces nesupravegheat pe acest PC - doar
  pregătește clientul ca să se poată conecta la laptopurile companiei.
#>
$ErrorActionPreference = "Stop"

# Aceleași valori ca în config.ps1 de pe flotă:
$RD_HOST  = "rustdesk.carpatica.local"
$RD_KEY   = "PUNETI_AICI_CHEIA_PUBLICA_id_ed25519.pub"
$RD_RELAY = $RD_HOST
$RD_API   = ""

function Get-InstalledExe {
    $p = Join-Path ${env:ProgramFiles} "RustDesk\rustdesk.exe"
    if (Test-Path $p) { return $p }
    return $null
}

# 1. Instalare client dacă lipsește (fără serviciu)
$exe = Get-InstalledExe
if (-not $exe) {
    $local = Join-Path $PSScriptRoot "rustdesk.exe"
    if (-not (Test-Path $local)) {
        Write-Host "Descarc clientul RustDesk..."
        $rel = Invoke-RestMethod "https://api.github.com/repos/rustdesk/rustdesk/releases/latest" -Headers @{ "User-Agent"="CarpaticaRemote" }
        $asset = $rel.assets | Where-Object { $_.name -match "x86_64\.exe$" } | Select-Object -First 1
        $local = Join-Path $env:TEMP "rustdesk-setup.exe"
        Invoke-WebRequest $asset.browser_download_url -OutFile $local -UseBasicParsing
    }
    Start-Process -FilePath $local -ArgumentList "--silent-install" -Wait
    Start-Sleep 12
    $exe = Get-InstalledExe
}
if (-not $exe) { throw "Clientul RustDesk nu s-a instalat." }

# 2. Aplică serverul companiei
Write-Host "Aplic serverul companiei în client..."
& $exe --option "custom-rendezvous-server" "$RD_HOST" | Out-Null
if ($RD_KEY -and $RD_KEY -ne "PUNETI_AICI_CHEIA_PUBLICA_id_ed25519.pub") {
    & $exe --option "key" "$RD_KEY" | Out-Null
} else {
    Write-Warning "Cheia publică nu a fost setată - completați `$RD_KEY."
}
if ($RD_RELAY) { & $exe --option "relay-server" "$RD_RELAY" | Out-Null }
if ($RD_API)   { & $exe --option "api-server"   "$RD_API"   | Out-Null }

Write-Host ""
Write-Host "Gata. Deschideți RustDesk, introduceți ID-ul și parola laptopului țintă."
Write-Host "ID-urile/parolele se iau din colectorul intern (vezi folderul collector)."
