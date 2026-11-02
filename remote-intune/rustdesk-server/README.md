# Server RustDesk (acces nesupravegheat) — instalare pe appsrv1

Pune serverul RustDesk (hbbs + hbbr) în Docker pe `appsrv1`, pentru **acces
nesupravegheat cu full admin** (vezi ecranul de login, UAC, supraviețuiește
reboot-ului — toate native RustDesk).

Fluxul complet:
```
Laptop (RustDesk serviciu) ──► raportează ID+parolă ──► serverul asistenta (tab „Dispozitive")
Tehnician (client RustDesk) ──► se conectează cu ID + parola ──► prin serverul RustDesk ──► laptop
```

**Separat** de stiva Caddy/`web` — RustDesk are porturile lui, nu trece prin Caddy.

---

## 1. Pornește serverul RustDesk pe appsrv1
```bash
cd ~/adrian && git pull origin main
ROOT=/srv/apps/rustdesk
sudo mkdir -p "$ROOT/data"
sudo cp ~/adrian/remote-intune/rustdesk-server/compose.yaml "$ROOT/compose.yaml"
sudo chown -R "$USER":"$USER" "$ROOT"
docker compose -f "$ROOT/compose.yaml" up -d
docker compose -f "$ROOT/compose.yaml" ps
```
Ambele containere (`rustdesk-hbbs`, `rustdesk-hbbr`) trebuie să fie `Up`.

## 2. Deschide porturile în firewall (doar pentru rețeaua internă/VPN)
RustDesk are nevoie de porturile lui direct pe host. Deschide-le **doar către
subrețelele interne/VPN** (nu spre internet):
```bash
# exemplu ufw — ajustează subrețelele la ale voastre (LAN + VPN)
for net in 172.17.17.0/24 192.168.2.0/24 10.40.0.0/24; do
  sudo ufw allow from $net to any port 21115:21119 proto tcp
  sudo ufw allow from $net to any port 21116 proto udp
done
sudo ufw status | grep 2111
```
> Dacă nu folosiți `ufw`, deschideți echivalent în firewall-ul vostru: TCP 21115-21119 + UDP 21116, din rețeaua internă/VPN.

## 3. Ia cheia publică a serverului (id_ed25519.pub)
hbbs generează o pereche de chei la prima pornire. Cheia **publică** se pune în
clienți și în instalatorul de pe laptopuri:
```bash
sudo cat /srv/apps/rustdesk/data/id_ed25519.pub
```
Copiază conținutul (o singură linie, fără ghilimele). **Cheia privată
(`id_ed25519`) rămâne pe server — nu o distribui.**

## 4. Completează instalatorul laptopurilor
În `remote-intune/unificat/config.ps1` pune:
```powershell
$SERVER_URL   = "https://asistenta.carpaticaferoviar.ro"   # deja setat
$INGEST_TOKEN = "<token de la: docker exec ... python -m server token>"
$RD_HOST      = "172.17.17.115"        # appsrv1 (serverul RustDesk)
$RD_KEY       = "<continutul id_ed25519.pub de la pasul 3>"
$RD_RELAY     = "172.17.17.115"
$RD_PASSWORD  = "random"               # fiecare laptop primeste parola proprie, raportata
```
Apoi împachetezi `remote-intune\unificat\` în Intune (vezi `unificat\README.md`).
Laptopurile vor instala RustDesk ca **serviciu** (nesupravegheat), configurat pe
serverul vostru, și vor raporta **ID + parola** la `/api/register` → apar în
consolă, tab **Dispozitive**.

## 5. Configurează clientul RustDesk al tehnicianului
Pe calculatorul tehnicianului, clientul RustDesk trebuie să arate spre **același**
server (ca să se întâlnească cu laptopurile). Folosește
`remote-intune/rustdesk/Configure-TechnicianClient.ps1` (sau manual în RustDesk →
Settings → Network: ID Server `172.17.17.115`, Relay `172.17.17.115`, Key =
`id_ed25519.pub`).

## 6. Conectarea (cum folosești)
1. În consolă → tab **Dispozitive** → găsești laptopul → **Arată parola**.
2. Deschizi clientul RustDesk → introduci **ID-ul** + **parola** → conectare.
3. Ai acces complet, nesupravegheat (inclusiv ecran de login, UAC, după reboot).

---

## Note
- Tehnicianul trebuie să fie și el pe rețeaua internă/VPN (ca să ajungă la
  `172.17.17.115` pe porturile RustDesk).
- Parolele dispozitivelor sunt criptate în repaus pe server și dezvăluite doar
  tehnicienilor autentificați; fiecare dezvăluire e în jurnalul de audit.
- Oprire: `docker compose -f /srv/apps/rustdesk/compose.yaml down` (datele rămân în `./data`).
