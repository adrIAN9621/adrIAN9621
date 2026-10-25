# Înrolarea laptopurilor deja folosite (fără resetare) în Entra + Intune

Pentru laptopurile care **se folosesc deja** (au date, aplicații, utilizatori) și NU
sunt în domeniu. Autopilot cere resetare → nepotrivit aici. Le înrolăm **fără wipe**.

Două metode. Recomandată e prima.

---

## Metoda A (recomandată) — Pachet de provisioning (.ppkg) cu înrolare în masă
Faci **UN singur fișier .ppkg** o dată, apoi îl rulezi pe fiecare laptop (dublu-clic,
sau îl împingi prin RustDesk / unealta de asistență). Laptopul se alătură la Entra +
Intune **fără resetare, fără pierdere de date**.

### 1. Creează pachetul (o singură dată)
1. Instalează **Windows Configuration Designer** (gratuit, din Microsoft Store).
2. **Provision desktop devices** (sau „Advanced").
3. **Account Management → Enroll in Azure AD → Get Bulk Token**:
   - te autentifici cu un **cont de administrator Entra** și accepți.
   - se creează un token de înrolare în masă (valabil o perioadă — ex. 180 zile).
4. (Opțional) nume dispozitiv după șablon (`CF0LP-%SERIAL%` — vezi nota de nume mai jos),
   WiFi, aplicații etc.
5. **Export → Provisioning package** → obții `Carpatica.ppkg` (+ eventual o parolă).

### 2. Rulează pe fiecare laptop (fără wipe)
- **Local:** dublu-clic pe `Carpatica.ppkg` → *Yes, add it* → repornește. Gata: Entra-joined
  + înrolat în Intune.
- **La distanță:** copiezi `.ppkg` pe laptop prin RustDesk / unealta de asistență și îl rulezi
  la fel — poți face toate cele 50 de la birou, pe rând, fără să te deplasezi.
- Comanda silențioasă (ex. pentru script):
  `Install-ProvisioningPackage -PackagePath C:\cale\Carpatica.ppkg -ForceInstall -QuietInstall`

### 3. După înrolare
Intune împinge automat politicile: **BitLocker, Secure Boot (remediere), conturi locale,
aplicații** (inclusiv agentul vostru / RustDesk). Numele `CF0LP+nume` îl pui cu scriptul
din `remote-intune/onboarding/` sau printr-o redenumire Intune.

---

## Metoda B — Manual „Access work or school" (1 laptop pe rând)
Pe fiecare laptop (direct sau prin RustDesk):
**Settings → Accounts → Access work or school → Connect → „Join this device to Microsoft
Entra"** → te loghezi cu contul admin → repornește. Se înrolează în Intune (dacă MDM
auto-enrollment e pornit — vezi `remote-intune/autopilot/README.md`, pasul 0).

Fără wipe, dar e manual pe fiecare — bun pentru câteva, nu pentru 50.

---

## De știut (important)
- **Profilul local rămâne.** Dispozitivul devine „corporate managed", dar profilul/utilizatorul
  local existent nu se șterge. Pentru valoare completă (SSO, Conditional Access), angajatul ar
  trebui apoi să se logheze cu **contul Entra**. Dacă vrei să muți datele din profilul local în
  cel Entra fără copiere manuală, se poate cu un utilitar de migrare profil (ex. User Profile
  Wizard) — opțional.
- **Licențe:** înrolarea în masă cere Entra ID P1 + Intune (de obicei incluse în M365 Business
  Premium / E3/E5).
- **Token-ul bulk expiră** (ex. 180 zile) — refaci `.ppkg` după expirare pentru loturi noi.

## Rezumat
| Situație | Soluție |
|---|---|
| 50 laptopuri în uz, fără wipe | **.ppkg bulk enrollment** (Metoda A), rulat local sau prin remote |
| Câteva laptopuri | „Access work or school" manual (Metoda B) |
| Laptopuri noi / resetabile | **Autopilot** (vezi folderul `autopilot/`) |
