# Secure Boot pe laptopuri Lenovo (V15 etc.) — din Windows, fără BIOS

Laptopurile Lenovo **V15 nu au Intel vPro**, deci nu poți vedea ecranul de BIOS de
la distanță. Dar **Secure Boot se poate activa din Windows** prin interfața WMI de
BIOS Lenovo — local, prin RustDesk/aplicația de asistență, sau cu Intune.

> Secure Boot cere **mod UEFI**. V15-urile noi cu Windows 11 sunt deja pe UEFI.
> Dacă vreunul e pe Legacy/CSM, întâi convertește: `mbr2gpt /convert /allowfullOS`
> apoi setează UEFI în BIOS. Altfel Secure Boot nu se poate activa.

## Variante de folosire

### 1. Pe un laptop (manual sau remote, PowerShell ca Administrator)
```powershell
powershell -ExecutionPolicy Bypass -File .\Enable-SecureBoot-Lenovo.ps1
# daca BIOS-ul are parola de supervisor:
powershell -ExecutionPolicy Bypass -File .\Enable-SecureBoot-Lenovo.ps1 -SupervisorPassword "PAROLA"
```
Apoi **repornește** laptopul. Verificare după repornire:
```powershell
Confirm-SecureBootUEFI   # trebuie sa dea True
```

### 2. Rapid, fără script (o linie)
```powershell
(Get-WmiObject -Namespace root\wmi -Class Lenovo_SetBiosSetting).SetBiosSetting("SecureBoot,Enable")
(Get-WmiObject -Namespace root\wmi -Class Lenovo_SaveBiosSettings).SaveBiosSettings("")
Restart-Computer
```

### 3. Intune — Remediations (la scară, pe toate laptopurile din domeniu)
- **Detection script:** `Detect-SecureBoot.ps1`
- **Remediation script:** `Enable-SecureBoot-Lenovo.ps1`
- Rulează în context **SYSTEM** (64-bit). Secure Boot se aplică la **următoarea repornire**.

## Note
- Numele setării diferă uneori între modele (`SecureBoot` / `Secure Boot`); scriptul
  îl detectează singur din lista BIOS.
- Dacă `SaveBiosSettings` eșuează cu parolă, rulează cu `-SupervisorPassword`.
- Alte setări BIOS Lenovo se pot citi/schimba la fel (boot order, virtualizare, TPM):
  `Get-WmiObject -Namespace root\wmi -Class Lenovo_BiosSetting | % { $_.CurrentSetting }`
