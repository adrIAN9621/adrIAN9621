# Windows Autopilot — laptopul nou se înrolează singur în Entra + Intune

Scop: pornești un laptop nou (sau resetat), angajatul se loghează o dată cu contul
Microsoft (Entra), iar laptopul se **înrolează singur** în Entra + Intune și primește
automat politicile (BitLocker, Secure Boot, aplicații, conturi etc.). Fără script pe
fiecare laptop.

> Necesită licențe care includ Intune + Entra ID P1 (ex. Microsoft 365 Business
> Premium, sau E3/E5). Dacă aveți Intune, aveți de regulă și astea.

## Pasul 0 — Activează înrolarea automată MDM (o singură dată)
Entra admin center → **Identity → Devices → Mobility (MDM)** → **Microsoft Intune**:
- **MDM user scope = All** (sau un grup pilot).
- Lași URL-urile implicite. Salvezi.

## Pasul 1 — Creează profilul Autopilot (o singură dată)
Intune (intune.microsoft.com) → **Devices → Enrollment → Windows → Deployment Profiles**
→ **Create profile → Windows PC**:
- **Deployment mode:** *User-driven* (recomandat) sau *Pre-provisioned* (tehnicianul
  pregătește, angajatul doar se loghează).
- **Join type:** **Microsoft Entra joined**.
- **Out-of-box (OOBE):** ascunde EULA, privacy, cont local; *Account type = Standard*;
  **Enrollment Status Page (ESP)** pornit (ca să aștepte aplicarea politicilor).
- **Device name template:** ex. `CF0LP-%SERIAL%` (vezi nota de mai jos despre nume).
- Atribuie profilul la un **grup** (ex. un grup dinamic cu toate dispozitivele Autopilot).

## Pasul 2 — Înregistrează laptopurile în Autopilot
Două variante:
- **A. Prin furnizor/Lenovo (ideal):** ceri la achiziție ca Lenovo să înregistreze
  laptopurile în tenant-ul vostru (OEM registration). Atunci nu mai faci nimic manual.
- **B. Manual (pentru ce ai deja):** pe fiecare laptop rulezi **`Collect-AutopilotHash.ps1`**
  (ca Administrator) → scoate un CSV cu amprenta → îl încarci în Intune:
  **Devices → Enrollment → Windows → Devices → Import**. (Sau direct: `-Online`.)

## Pasul 3 — Politicile care fac restul (o singură dată, se aplică la toți)
Intune → **Devices → Configuration / Compliance / Scripts and remediations**:
- **BitLocker:** Endpoint security → **Disk encryption** (XTS-AES-256, salvează cheia în Entra).
- **Secure Boot / conturi locale / redenumire:** **Remediations** (Detect+Remediate) —
  pot fi exact scripturile din `remote-intune/bios-lenovo/` și `remote-intune/onboarding/`
  adaptate.
- **Aplicații** (inclusiv agentul vostru de asistență / RustDesk) ca Win32 apps.

## Pasul 4 — Prima pornire
Laptop nou/resetat → conectezi la rețea → vede profilul Autopilot → angajatul se loghează
cu contul Entra → se înrolează singur → ESP aplică politicile și aplicațiile → gata.

Pentru laptopurile existente: le **resetezi** (Settings → Recovery → Reset, „Remove
everything") după ce le-ai înregistrat la pasul 2, și pornesc în flux Autopilot.

---

## Notă importantă despre numele calculatorului
Autopilot **nu știe numele angajatului**, deci poate numi doar cu șablon (serial/aleator),
ex. `CF0LP-%SERIAL%`. Convenția voastră `CF0LP + NUME + inițială` (ex. `CF0LPVLASINA`) ține
de persoană → se pune fie din **scriptul de onboarding** (`remote-intune/onboarding/`),
fie printr-o redenumire ulterioară în Intune. Autopilot + scriptul vostru se completează.
