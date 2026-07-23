# Monitoring Bot & ZiVPN Manager 🛡️

Bot Telegram tout-en-un pour surveiller votre serveur Linux en temps réel et gérer des accès VPN (ZiVPN UDP) et SSH (Payload TCP) depuis votre téléphone.

## Fonctionnalités Principales

### 📈 Monitoring Serveur
| Commande | Description |
|----------|-------------|
| `/status` | Tableau de bord complet (CPU, RAM, disque, réseau, uptime) |
| `/system` | Informations système (OS, kernel, arch, boot) |
| `/cpu` | Utilisation CPU, charge, fréquence, cœurs |
| `/ram` | RAM et Swap (total, utilisé, libre) |
| `/disk` | Disque et entrées/sorties |
| `/gpu` | GPU NVIDIA (usage, VRAM, température) |
| `/network` | Statistiques réseau par interface + vitesse temps réel |

**Alertes automatiques** : CPU > 80%, RAM > 85%, Disque > 85%.

### 🔐 Gestionnaire VPN — `/vpn`
Commande interactive pour votre serveur **ZiVPN (UDP)** :
- **ON/OFF** : Démarrer/Stopper le service `zivpn.service` depuis Telegram
- **Création** : Utilisateur → Mot de passe → Expiration par boutons (+1j, +7j...) + choix de l'heure
- **Gestion** : Modifier mot de passe, prolonger expiration (boutons), supprimer
- **Verrouillage auto** : Les comptes expirés sont verrouillés automatiquement à la minute près (pas de double alerte)

### 🛡️ Gestionnaire SSH Payload — `/ssh`
Commande interactive pour votre **Proxy SSH Custom** (HTTP Injection + SSL Passthrough) :
- **Double Proxy** : HTTP Injection (Port `2053`) + SSL Passthrough (Port `8443`)
- **ON/OFF** : Démarrer/Stopper `ssh-proxy.service` depuis Telegram
- **Création** : User → Pass → Expiration par boutons → **Limite connexions max** → **Quota data (MB)**
- **Limites de connexion** : Contrôle via PAM (`/etc/security/limits.conf`) — le système Linux refuse la Nième connexion
- **Quota data** : Tracking par iptables (par UID) — le bot cumule les octets toutes les 60s et verrouille le compte si dépassement
- **Parsing robuste** : Détecte `SSH-2.0` dans le payload, compatible HA Tunnel Plus, HTTP Injector, HTTP Custom...
- **Expiration automatique** : Vérification précise chaque minute, verrouillage immédiat

### 🔑 Accès invité — `/grant` & `/auth`
Le bot est privé (admin seulement par défaut) :
- `/grant` (admin) : Génère un code à usage unique de 8 caractères
- `/auth CODE` (invité) : Accède au monitoring uniquement (pas de gestion VPN/SSH)

---

## 🚀 Installation "All-In-One" (Recommandé)

Le script `install.sh` détecte votre architecture (amd64, arm64, arm), installe **tout** automatiquement :

```bash
git clone https://github.com/TheShellMaster/monitoring-bot.git
cd monitoring-bot
sudo bash install.sh
```

**Ce que le script fait :**
1. Installe les dépendances (Python, OpenSSH, iptables, tzdata...)
2. Télécharge ZiVPN pour votre architecture dans `/usr/local/bin/`
3. Génère les certificats SSL dans `/etc/zivpn/`
4. Configure ZiVPN sur le port **443 UDP**
5. Configure les permissions sudoers (bot → systemctl, useradd, iptables, sed...)
6. Active `PasswordAuthentication` dans OpenSSH
7. Ouvre les ports dans le firewall (ufw / firewalld / iptables)
8. Crée l'environnement Python et installe les dépendances
9. Valide votre token Telegram via l'API avant de continuer
10. Configure le fuseau horaire (via `tzselect`)
11. Crée les services systemd : `monitoring-bot.service`, `zivpn.service`, `ssh-proxy.service`
12. Sauvegarde les règles iptables (`iptables-persistent`)

*(Le script vous demandera votre Token Telegram, le fuseau horaire, l'ID admin Telegram et le nom d'utilisateur système).*

---

## ⚙️ Installation Manuelle

Si vous préférez (sans ZiVPN, sans proxy SSH) :

```bash
git clone https://github.com/TheShellMaster/monitoring-bot.git
cd monitoring-bot
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
echo "TELEGRAM_BOT_TOKEN=votre_token_ici" > .env_bot
echo "TZ=Ville/Continent" >> .env_bot   # ex: Africa/Douala
./venv/bin/python3 monitoring-bot.py
```

## Obtenir un token Telegram
1. Ouvrez Telegram et cherchez [@BotFather](https://t.me/BotFather)
2. Envoyez `/newbot`
3. Choisissez un nom et un username (ex: `mon_serveur_bot`)
4. Copiez le token reçu (ex: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

## Compatibilité

| Composant | Architecture |
|-----------|-------------|
| ZiVPN | Linux x86_64, ARM64, ARM |
| SSH Proxy | Linux (Python asyncio) |
| Bot | Linux, Windows, macOS |

---

*Tags : Telegram Bot, Server Monitoring, ZiVPN Manager, UDP VPN, VPN CRM, SysAdmin, DevOps, Python, Botfather, psutil, Linux Server, Ubuntu VPN Setup, HA Tunnel Plus, HTTP Injector, SSH Payload, SSH Proxy, SNI Spoofing, TCP Custom, SSH Limits, iptables quota, PAM maxlogins, Free Internet Payload.*
