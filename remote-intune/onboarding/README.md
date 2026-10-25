# Onboarding laptop Carpatica Feroviar

Un singur pas pentru punerea în folosință a unui laptop nou (Lenovo V15 etc.):
redenumire → alăturare la „work" → Secure Boot → criptare date (BitLocker) → repornire.

## Cum se folosește
1. Editează **`config.ps1`** și pune:
   - `$AdminPassword` – parola contului `adm_bogdana@carpaticaferoviar.ro`;
   - `$JoinMode` – `"Entra"` (Azure AD / Access work or school, cel cu Intune) sau `"AD"` (domeniu on-prem);
   - (pentru AD) `$DomainName`.
2. Click dreapta pe **`Onboard-Laptop.bat`** → **Run as administrator**.
3. Scrie **numele de familie** și **prenumele** → numele calculatorului se face automat:
   `CF0LP` + NUME + inițiala prenumelui (ex. *Vlasin Adrian* → **CF0LPVLASINA**).
4. Urmează pașii; la final repornește.

## Ce face, în ordine
1. **Redenumire** calculator (`CF0LP<NUME><initiala>`, max 15 caractere, fără diacritice).
2. **Alăturare la work:**
   - `AD` → complet automat (`Add-Computer` cu contul din `config.ps1`).
   - `Entra` → deschide „Access work or school"; **alăturarea cu cont+parolă NU se poate
     face silențios** (limitare Microsoft), deci completezi tu în fereastra Setări cu
     contul afișat (parola e în `config.ps1`), apoi apeși Enter ca să continue.
3. **Secure Boot** – activat din Windows prin WMI-ul BIOS Lenovo (se aplică la repornire).
4. **Criptare date (BitLocker)** pe `C:` (XTS-AES-256), cu **cheie de recuperare**:
   - salvată în Entra/AD (dacă e alăturat) **și** într-un fișier `BitLocker-<nume>.txt`
     (în `$BitLockerKeyFolder` sau pe desktop-ul public).
5. **Repornire** – aplică redenumirea + Secure Boot.

## De ce e importantă ordinea
BitLocker se activează **după** ce se setează Secure Boot, iar scriptul **suspendă
BitLocker pentru 2 reporniri** (`Suspend-BitLocker -RebootCount 2`). Altfel, când Secure
Boot se aplică la repornire, se schimbă măsurătorile TPM și BitLocker ar cere **cheia de
recuperare** la fiecare boot. Așa nu se întâmplă.

## Cerințe
- Laptop **Lenovo** cu interfața WMI BIOS (V15 o are), **TPM 2.0** activ, disc **GPT/UEFI**
  (V15 nou cu Win11 e deja UEFI; dacă e Legacy: `mbr2gpt /convert /allowfullOS` întâi).
- Rulat ca **Administrator**.
- Dacă BIOS-ul are **parolă de supervisor**, Secure Boot se setează manual sau se extinde
  scriptul cu `SaveBiosSettings("parola,ascii,us")`.

## Siguranță (NIS2)
- Păstrează `config.ps1` cu parola **doar temporar** și șterge parola după folosire (sau
  folosește o parolă dedicată de onboarding, rotită des).
- Cheile de recuperare BitLocker: păstrează-le în Entra/AD, nu doar în fișier.
