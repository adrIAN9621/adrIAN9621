<#
  Carpatica Feroviar - instalare RustDesk cu acces nesupravegheat.

  Rulează ca SYSTEM (Intune) sau ca administrator (manual). Instalează RustDesk
  ca serviciu Windows, aplică serverul companiei și setează parola de acces
  nesupravegheat, apoi raportează ID-ul și parola.

  Funcționează și când se schimbă utilizatorii și la ecranul de logon, pentru că
  serviciul rulează ca SYSTEM.

  Jurnal: C:\ProgramData\CarpaticaRemote\install.log
  Date laptop: C:\ProgramData\CarpaticaRemote\device-info.txt
#>

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\config.ps1"

$DataDir = Join-Path $env:ProgramData "CarpaticaRemote"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$LogFile = Join-Path $DataDir "install.log"

function Log($m) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m
    Add-Content -Path $LogFile -Value $line
    Write-Output $line
}

function Get-RustDeskExe {
    # Preferă exe-ul bundelat lângă script.
    $local = Join-Path $PSScriptRoot "rustdesk.exe"
    if (Test-Path $local) { Log "Folosesc rustdesk.exe bundelat."; return $local }
    if (-not $RD_FALLBACK_DOWNLOAD) { throw "rustdesk.exe lipsește și descărcarea e dezactivată." }

    Log "Descarc ultima versiune RustDesk de pe GitHub..."
    $api = "https://api.github.com/repos/rustdesk/rustdesk/releases/latest"
    $rel = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "CarpaticaRemote" }
    $asset = $rel.assets | Where-Object { $_.name -match "x86_64\.exe$" } | Select-Object -First 1
    if (-not $asset) { throw "Nu am găsit instalerul x86_64 în release-ul GitHub." }
    $dest = Join-Path $DataDir "rustdesk-setup.exe"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $dest -UseBasicParsing
    Log ("Descărcat: {0}" -f $asset.name)
    return $dest
}

function Get-InstalledExe {
    $p = Join-Path ${env:ProgramFiles} "RustDesk\rustdesk.exe"
    if (Test-Path $p) { return $p }
    return $null
}

function New-RandomPassword($len) {
    $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789".ToCharArray()
    -join (1..$len | ForEach-Object { $chars | Get-Random })
}

try {
    Log "=== Instalare $RD_PRODUCT ==="
    $isSystem = ([Security.Principal.WindowsIdentity]::GetCurrent()).IsSystem
    Log ("Context: {0}" -f (([Security.Principal.WindowsIdentity]::GetCurrent()).Name))

    # 1. Instalare silențioasă
    $setup = Get-RustDeskExe
    if (-not (Get-InstalledExe)) {
        Log "Rulez instalarea silențioasă..."
        Start-Process -FilePath $setup -ArgumentList "--silent-install" -Wait
        Start-Sleep -Seconds 15
    } else {
        Log "RustDesk este deja instalat; continui cu configurarea."
    }
    $exe = Get-InstalledExe
    if (-not $exe) { throw "RustDesk nu s-a instalat în Program Files." }

    # 2. Serviciul Windows (acces la logon / UAC / schimbare de user)
    if ($RD_INSTALL_SERVICE) {
        $svc = Get-Service -Name "RustDesk" -ErrorAction SilentlyContinue
        if (-not $svc) {
            Log "Instalez serviciul RustDesk..."
            Start-Process -FilePath $exe -ArgumentList "--install-service" -Wait
            Start-Sleep -Seconds 10
        }
        Set-Service -Name "RustDesk" -StartupType Automatic -ErrorAction SilentlyContinue
        $n = 0
        while ((Get-Service -Name "RustDesk").Status -ne "Running" -and $n -lt 10) {
            Start-Service -Name "RustDesk" -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3; $n++
        }
        Log ("Serviciu RustDesk: {0}" -f (Get-Service -Name "RustDesk").Status)
    }

    # 3. Configurare server (gazda, cheia, releul, api)
    Log "Aplic configurația serverului companiei..."
    & $exe --option "custom-rendezvous-server" "$RD_HOST" | Out-Null
    if ($RD_KEY   -and $RD_KEY -ne "PUNETI_AICI_CHEIA_PUBLICA_id_ed25519.pub") {
        & $exe --option "key" "$RD_KEY" | Out-Null
    } else {
        Log "ATENȚIE: cheia publică nu a fost setată în config.ps1 - conexiunile criptate pot eșua."
    }
    if ($RD_RELAY) { & $exe --option "relay-server" "$RD_RELAY" | Out-Null }
    if ($RD_API)   { & $exe --option "api-server"   "$RD_API"   | Out-Null }

    # 4. Mod de acces nesupravegheat
    Log "Configurez accesul nesupravegheat (approve-mode=$RD_APPROVE_MODE)..."
    & $exe --option "verification-method" "use-permanent-password" | Out-Null
    & $exe --option "approve-mode" "$RD_APPROVE_MODE" | Out-Null

    # 5. Parola permanentă
    $pw = $RD_PASSWORD
    if ($pw -eq "random") { $pw = New-RandomPassword $RD_RANDOM_LEN }
    & $exe --password "$pw" | Out-Null
    Log "Parola de acces nesupravegheat a fost setată."

    # 6. Citește ID-ul
    Start-Sleep -Seconds 3
    $id = (& $exe --get-id | Select-Object -First 1).Trim()
    Log ("ID calculator: {0}" -f $id)

    # 7. Salvează și raportează
    $hostname = $env:COMPUTERNAME
    $info = [ordered]@{
        product  = $RD_PRODUCT
        id       = $id
        password = $pw
        hostname = $hostname
        server   = $RD_HOST
        time     = (Get-Date -Format "s")
    }
    $info.GetEnumerator() | ForEach-Object { "{0}={1}" -f $_.Key, $_.Value } |
        Set-Content -Path (Join-Path $DataDir "device-info.txt") -Encoding UTF8
    Log "Am salvat device-info.txt."

    if ($RD_REPORT_URL) {
        try {
            $headers = @{}
            if ($RD_REPORT_TOKEN) { $headers["Authorization"] = "Bearer $RD_REPORT_TOKEN" }
            Invoke-RestMethod -Uri $RD_REPORT_URL -Method Post -ContentType "application/json" `
                -Headers $headers -Body ($info | ConvertTo-Json) -TimeoutSec 20 | Out-Null
            Log "Raportat către $RD_REPORT_URL."
        } catch {
            Log ("Raportarea a eșuat (nu e critic): {0}" -f $_.Exception.Message)
        }
    }

    Log "=== Instalare finalizată cu succes ==="
    exit 0
}
catch {
    Log ("EROARE: {0}" -f $_.Exception.Message)
    Log ($_.ScriptStackTrace)
    exit 1
}
