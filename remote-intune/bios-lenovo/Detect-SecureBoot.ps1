<#
  Detect-SecureBoot.ps1  (pentru Intune Remediations - scriptul de DETECTIE)
  Iese 0 daca Secure Boot e PORNIT (conform), 1 daca e OPRIT (declanseaza remedierea).
#>
try {
    if (Confirm-SecureBootUEFI) {
        Write-Output "Secure Boot: PORNIT"
        exit 0
    }
    Write-Output "Secure Boot: OPRIT"
    exit 1
}
catch {
    # Legacy/BIOS sau necunoscut -> tratam ca neconform
    Write-Output "Secure Boot: indisponibil (posibil mod Legacy/non-UEFI)"
    exit 1
}
