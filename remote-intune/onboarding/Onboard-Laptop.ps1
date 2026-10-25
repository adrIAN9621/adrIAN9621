<#
  Onboard-Laptop.ps1 — onboarding laptop Carpatica Feroviar (Lenovo V15 etc.)
  Pasi, in ordine:
    1) Intreaba numele si redenumeste calculatorul (PREFIX + NUME + initiala prenume).
    2) Alatura laptopul la "work" (Entra / Azure AD, sau domeniu on-prem AD).
    3) Activeaza Secure Boot (BIOS Lenovo prin WMI).
    4) Activeaza criptarea datelor (BitLocker) — cu cheie de recuperare salvata.
    5) Reporneste (aplica redenumire + Secure Boot; BitLocker e suspendat corect
       peste repornire ca sa NU ceara cheia de recuperare).

  Rulare: click dreapta pe Onboard-Laptop.bat -> Run as administrator.
  Valorile (cont, parola, tip join) se pun in config.ps1 de langa acest fisier.
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\config.ps1"

function Log($m) { Write-Host ("[Onboard] " + $m) }
function Warn($m) { Write-Warning ("[Onboard] " + $m) }

function Normalize([string]$s) {
    if (-not $s) { return "" }
    $d = $s.Normalize([Text.NormalizationForm]::FormD)
    $sb = New-Object System.Text.StringBuilder
    foreach ($c in $d.ToCharArray()) {
        if ([Globalization.CharUnicodeInfo]::GetUnicodeCategory($c) -ne [Globalization.UnicodeCategory]::NonSpacingMark) {
            [void]$sb.Append($c)
        }
    }
    return (($sb.ToString() -replace '[^A-Za-z0-9]', '').ToUpper())
}

# ------------------------------------------------------------------ 1. NUME
Write-Host ""
Write-Host "=== Onboarding laptop Carpatica Feroviar ===" -ForegroundColor Cyan
$nume = Read-Host "Numele de familie (ex. Vlasin)"
$prenume = Read-Host "Prenumele (ex. Adrian)"
$n = Normalize $nume
$p = Normalize $prenume
if (-not $n -or -not $p) { throw "Nume/prenume invalid." }
$hostName = ($NamePrefix + $n + $p.Substring(0, 1))
if ($hostName.Length -gt 15) { $hostName = $hostName.Substring(0, 15) }  # limita Windows
Write-Host ""
Write-Host ("Numele calculatorului va fi:  " + $hostName) -ForegroundColor Yellow
if ((Read-Host "Confirmati? (D/N)") -notmatch '^[DdYy]') { Log "Anulat."; exit 1 }

# ------------------------------------------------------------------ 2. JOIN + REDENUMIRE
if ($AdminPassword -eq "PUNETI_PAROLA_AICI" -or -not $AdminPassword) {
    throw "Puneti parola contului administrativ in config.ps1 ($AdminUser)."
}
$sec = ConvertTo-SecureString $AdminPassword -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential($AdminUser, $sec)

if ($JoinMode -eq "AD") {
    Log "Alatur la domeniul on-prem $DomainName si redenumesc in $hostName ..."
    Add-Computer -DomainName $DomainName -Credential $cred -NewName $hostName -Force
    Log "Alaturat la domeniu + redenumit (se aplica la repornire)."
}
else {
    # Entra / Azure AD: alaturarea cu cont+parola NU se poate face silentios (nesuportat).
    Log "Redenumesc in $hostName ..."
    Rename-Computer -NewName $hostName -Force
    Log "Deschid 'Access work or school' pentru alaturare la Microsoft Entra."
    Log ("Folositi contul:  " + $AdminUser + "   (parola e in config.ps1)")
    Start-Process "ms-settings:workplace"
    Read-Host "Dupa ce ati terminat alaturarea la Entra in fereastra Setari, apasati Enter aici"
}

# ------------------------------------------------------------------ 2b. CONTURI LOCALE (hardening NIS2)
# Redenumeste contul Administrator integrat (SID ...-500) si dezactiveaza Guest
# (SID ...-501). Tintim dupa SID ca sa mearga si pe Windows in alta limba.
try {
    if ($RenameAdminTo) {
        $admin = Get-LocalUser | Where-Object { $_.SID.Value.EndsWith("-500") } | Select-Object -First 1
        if ($admin) {
            if ($admin.Name -ne $RenameAdminTo) {
                Rename-LocalUser -Name $admin.Name -NewName $RenameAdminTo
                Log "Contul Administrator redenumit in '$RenameAdminTo'."
            }
            else { Log "Contul administrator e deja '$RenameAdminTo'." }
        }
        else { Warn "Nu am gasit contul Administrator local (-500)." }
    }
}
catch { Warn "Redenumire Administrator: $($_.Exception.Message)" }

try {
    if ($DisableGuest) {
        $guest = Get-LocalUser | Where-Object { $_.SID.Value.EndsWith("-501") } | Select-Object -First 1
        if ($guest) {
            if ($guest.Enabled) { Disable-LocalUser -Name $guest.Name; Log "Contul Guest / Oaspete dezactivat." }
            else { Log "Contul Guest / Oaspete e deja dezactivat." }
        }
        else { Log "Nu exista cont Guest (ok)." }
    }
}
catch { Warn "Dezactivare Guest: $($_.Exception.Message)" }

# ------------------------------------------------------------------ 3. SECURE BOOT
Log "Activez Secure Boot (BIOS Lenovo)..."
try {
    $already = $false
    try { $already = Confirm-SecureBootUEFI } catch { $already = $false }
    if ($already) {
        Log "Secure Boot este deja activat."
    }
    else {
        $settings = Get-WmiObject -Namespace root\wmi -Class Lenovo_BiosSetting
        $sbName = $null
        foreach ($s in $settings) {
            if ($s.CurrentSetting -match '^(Secure\s?Boot)\s*,') { $sbName = ($s.CurrentSetting -split ',')[0]; break }
        }
        if ($sbName) {
            $set = Get-WmiObject -Namespace root\wmi -Class Lenovo_SetBiosSetting
            $save = Get-WmiObject -Namespace root\wmi -Class Lenovo_SaveBiosSettings
            $r = $set.SetBiosSetting("$sbName,Enable")
            if ($r.Return -ne "Success") { Warn "SetBiosSetting: $($r.Return)" }
            $rs = $save.SaveBiosSettings("")
            if ($rs.Return -ne "Success") { Warn "SaveBiosSettings: $($rs.Return) (daca BIOS-ul are parola de supervisor, setati Secure Boot manual)" }
            else { Log "Secure Boot setat pe Enable (se aplica la repornire)." }
        }
        else { Warn "Nu am gasit setarea Secure Boot in BIOS-ul acestui model (poate nu e Lenovo sau e mod Legacy)." }
    }
}
catch { Warn "Secure Boot: $($_.Exception.Message)" }

# ------------------------------------------------------------------ 4. CRIPTARE (BitLocker)
Log "Activez criptarea datelor (BitLocker) pe C: ..."
try {
    $vol = Get-BitLockerVolume -MountPoint "C:"
    if ($vol.ProtectionStatus -eq "On") {
        Log "BitLocker este deja pornit pe C:."
    }
    else {
        # protector de recuperare (cheie) + protector TPM
        Add-BitLockerKeyProtector -MountPoint "C:" -RecoveryPasswordProtector | Out-Null
        Enable-BitLocker -MountPoint "C:" -EncryptionMethod XtsAes256 -TpmProtector -SkipHardwareTest -ErrorAction Stop
        Log "BitLocker pornit."
    }
    # salvam cheia de recuperare
    $rk = (Get-BitLockerVolume -MountPoint "C:").KeyProtector |
    Where-Object { $_.KeyProtectorType -eq "RecoveryPassword" } | Select-Object -First 1
    if ($rk) {
        # backup in Entra/AD (daca e alaturat)
        try { BackupToAAD-BitLockerKeyProtector -MountPoint "C:" -KeyProtectorId $rk.KeyProtectorId -ErrorAction Stop; Log "Cheie salvata in Entra/AD." } catch {}
        $folder = if ($BitLockerKeyFolder) { $BitLockerKeyFolder } else { "$env:PUBLIC\Desktop" }
        try {
            if (-not (Test-Path $folder)) { New-Item -ItemType Directory -Path $folder -Force | Out-Null }
            $file = Join-Path $folder ("BitLocker-" + $hostName + ".txt")
            "Laptop: $hostName`r`nCheie recuperare BitLocker: $($rk.RecoveryPassword)`r`nData: $(Get-Date)" | Out-File -FilePath $file -Encoding UTF8
            Log ("Cheie de recuperare salvata in: " + $file + "  (pastrati-o in siguranta!)")
        }
        catch { Warn "Nu am putut salva cheia in fisier: $($_.Exception.Message)" }
    }
    # suspendam protectia peste repornirile care aplica Secure Boot + redenumire,
    # ca schimbarea masuratorilor TPM sa NU declanseze ecranul de recuperare.
    Suspend-BitLocker -MountPoint "C:" -RebootCount 2 | Out-Null
    Log "BitLocker suspendat pentru 2 reporniri (se reactiveaza automat apoi)."
}
catch { Warn "BitLocker: $($_.Exception.Message)  (verificati TPM 2.0 activ si ca discul e GPT/UEFI)" }

# ------------------------------------------------------------------ 5. REPORNIRE
Write-Host ""
Log "Gata. Repornesc pentru a aplica redenumirea + Secure Boot."
Log "Dupa repornire, verificati:  Confirm-SecureBootUEFI (True)  si  Get-BitLockerVolume C:"
if ((Read-Host "Repornesc acum? (D/N)") -match '^[DdYy]') {
    Restart-Computer -Force
}
else {
    Log "Reporniti manual cat mai curand ca sa se aplice setarile."
}
