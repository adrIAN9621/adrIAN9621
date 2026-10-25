<#
  Enable-SecureBoot-Lenovo.ps1
  Activeaza Secure Boot pe laptopuri Lenovo (V15 etc.) prin interfata WMI BIOS,
  DIN WINDOWS - fara a intra in ecranul de BIOS. Rulabil:
    - local (PowerShell ca Administrator),
    - prin RustDesk / aplicatia de asistenta (remote),
    - ca remediere Intune (Remediations).

  Parametru optional:
    -SupervisorPassword "parola"   daca BIOS-ul are parola de supervisor.

  NOTA: Secure Boot cere mod UEFI. Daca laptopul e in Legacy/CSM, convertiti
  intai discul la GPT/UEFI (mbr2gpt /convert) si setati UEFI in BIOS.
#>
#Requires -RunAsAdministrator
param(
    [string]$SupervisorPassword = ""
)

function Log($m) { Write-Host "[Secure Boot] $m" }

# 1. Secure Boot deja activ? Si suntem pe UEFI?
try {
    if (Confirm-SecureBootUEFI) {
        Log "Secure Boot este DEJA activat. Nimic de facut."
        exit 0
    }
    Log "Secure Boot este dezactivat (firmware UEFI). Continuam."
}
catch {
    Log "ATENTIE: sistemul pare in mod Legacy/BIOS (nu UEFI) sau comanda nu e suportata."
    Log "Secure Boot NU se poate activa in Legacy. Convertiti intai la UEFI (mbr2gpt) si reveniti."
    # incercam totusi setarea; daca nu e UEFI, nu se va aplica
}

# 2. Interfata WMI BIOS Lenovo
$ns = "root\wmi"
try {
    $settings = Get-WmiObject -Namespace $ns -Class Lenovo_BiosSetting -ErrorAction Stop
}
catch {
    Log "EROARE: interfata WMI BIOS Lenovo nu e disponibila pe acest model. Opresc."
    exit 1
}

# 3. Gasim numele exact al setarii Secure Boot (variaza intre modele)
$name = $null; $current = $null
foreach ($s in $settings) {
    if ($s.CurrentSetting -match '^(Secure\s?Boot)\s*,') {
        $name = ($s.CurrentSetting -split ',')[0]
        $current = $s.CurrentSetting
        break
    }
}
if (-not $name) {
    Log "Nu am gasit setarea Secure Boot in BIOS-ul acestui model."
    exit 1
}
Log "Setare gasita: $current"

# 4. Setam pe Enable si salvam
$set = Get-WmiObject -Namespace $ns -Class Lenovo_SetBiosSetting
$save = Get-WmiObject -Namespace $ns -Class Lenovo_SaveBiosSettings

$r1 = $set.SetBiosSetting("$name,Enable")
if ($r1.Return -ne "Success") {
    Log "SetBiosSetting a esuat: $($r1.Return)"
    exit 1
}

if ($SupervisorPassword) {
    $r2 = $save.SaveBiosSettings("$SupervisorPassword,ascii,us")
}
else {
    $r2 = $save.SaveBiosSettings("")
}
if ($r2.Return -ne "Success") {
    Log "SaveBiosSettings a esuat: $($r2.Return)."
    Log "Daca BIOS-ul are parola de supervisor, rulati cu -SupervisorPassword 'parola'."
    exit 1
}

Log "Secure Boot setat pe Enable. REPORNITI laptopul pentru a aplica."
Log "Dupa repornire verificati cu:  Confirm-SecureBootUEFI   (trebuie sa dea True)."
exit 0
