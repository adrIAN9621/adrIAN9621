# ============================================================
#  Configurare onboarding laptop Carpatica Feroviar
#  Completati valorile de mai jos, apoi rulati Onboard-Laptop.bat
#  (click dreapta -> Run as administrator).
# ============================================================

# Contul administrativ cu care se alatura laptopul la "work" (domeniu).
$AdminUser     = "adm_bogdana@carpaticaferoviar.ro"
$AdminPassword = "PUNETI_PAROLA_AICI"

# Tipul de alaturare:
#   "Entra" = Microsoft Entra / Azure AD ("Access work or school")  -> cel cu Intune
#   "AD"    = domeniu on-prem clasic (Active Directory)
$JoinMode = "Entra"

# Doar pentru $JoinMode = "AD":
$DomainName = "carpaticaferoviar.ro"

# Unde se salveaza cheia de recuperare BitLocker (optional, dar recomandat).
# Lasati gol ("") ca sa se salveze doar in Entra/AD + pe desktop-ul public.
$BitLockerKeyFolder = ""

# Prefixul numelui calculatorului. Numele final = PREFIX + NUME + initiala prenume.
# Ex.: Vlasin Adrian -> CF0LPVLASINA
$NamePrefix = "CF0LP"

# Securizare conturi locale (recomandat NIS2):
$RenameAdminTo = "supervizor"   # redenumeste contul Administrator (gol "" = nu schimba)
$DisableGuest  = $true          # dezactiveaza contul Guest / Oaspete
