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
Commande interactive pour votre **Proxy SSH Custom** (HTTP Injection + SSL/TLS) :
- **Double Proxy** : HTTP Injection (Port `2053`) + SSL/TLS avec SNI (Port `8443`)
- **ON/OFF** : Démarrer/Stopper `ssh-proxy.service` depuis Telegram
- **Création** : User → Pass → Expiration par boutons → **Limite connexions max** → **Quota data (MB)**
- **Limites de connexion** : Contrôle via PAM (`/etc/security/limits.conf`) — le système Linux refuse la Nième connexion
- **Quota data** : Tracking par iptables (`OUTPUT` par UID) — le bot cumule les octets toutes les 60s et verrouille le compte si dépassement
- **Parsing robuste** : Détecte `SSH-2.0` dans le payload, compatible HA Tunnel Plus, HTTP Injector, HTTP Custom...
- **Expiration automatique** : Vérification précise chaque minute, verrouillage immédiat

### 🔑 Accès invité — `/grant` & `/auth`
Le bot est privé (admin seulement par défaut) :
- `/grant` (admin) : Génère un code à usage unique de 8 caractères
- `/auth CODE` (invité) : Accède au monitoring uniquement (pas de gestion VPN/SSH)

---

## Installation tout-en-un

L'installation cible un serveur Linux Debian/Ubuntu avec accès Internet, `sudo` et systemd. Elle installe les dépendances, ZiVPN, le proxy SSH, le bot Telegram, les services systemd, les groupes de comptes et les règles firewall.

Le script `install.sh` détecte votre architecture (amd64, arm64, arm), installe **tout** automatiquement :

```bash
git clone https://github.com/TheShellMaster/monitoring-bot.git
cd monitoring-bot
bash install.sh
```

Le script demande les privilèges `sudo` quand nécessaire. Il ne faut pas exécuter le dépôt avec `sudo git clone`, afin que l'utilisateur du service puisse lire les fichiers du projet.

**Ce que le script fait :**
1. Installe les dépendances (Python, OpenSSH, iptables, tzdata...)
2. Télécharge ZiVPN pour votre architecture dans `/usr/local/bin/`
3. Génère les certificats SSL dans `/etc/zivpn/`
4. Configure ZiVPN sur le port **443 UDP**
5. Configure les permissions sudoers nécessaires au bot et valide leur syntaxe
6. Désactive l'authentification SSH par mot de passe globalement et l'autorise uniquement pour les membres du groupe SSH dédié
7. Ouvre les ports dans le firewall (ufw / firewalld / iptables)
8. Crée l'environnement Python et installe les dépendances
9. Valide votre token Telegram via l'API avant de continuer
10. Configure le fuseau horaire (via `tzselect`)
11. Crée les services systemd : `monitoring-bot.service`, `zivpn.service`, `ssh-proxy.service`
12. Sauvegarde les règles iptables (`iptables-persistent`)

Le script demande le token Telegram, le fuseau horaire, l'ID admin Telegram et l'utilisateur système des services. Le fichier `.env_bot` est créé avec les permissions `600` et n'est pas versionné.

Les groupes sont configurables avant l'installation :

```bash
SSH_USERS_GROUP=sshusers VPN_USERS_GROUP=vpnusers bash install.sh
```

Les bases SQLite sont stockées à côté du code (`ssh_accounts.db` et `vpn_accounts.db`). Les gestionnaires resynchronisent les groupes Linux depuis ces bases au démarrage; un ancien membre d'un groupe dédié est retiré automatiquement.

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

Cette méthode ne configure pas ZiVPN, le proxy SSH, OpenSSH, sudoers ou le firewall. Pour un serveur complet, utilisez `install.sh`.

## Vérification après installation

```bash
sudo systemctl is-active monitoring-bot.service zivpn.service ssh-proxy.service ssh
sudo sshd -T -C user=compte_ssh,host=localhost,addr=127.0.0.1 \
  | grep -E 'passwordauthentication|pubkeyauthentication'
getent group sshusers vpnusers
```

Un compte SSH doit appartenir au groupe SSH configuré et avoir `passwordauthentication yes`. Un compte ZiVPN doit appartenir au groupe VPN configuré et avoir `passwordauthentication no` côté OpenSSH.

## Obtenir un token Telegram
1. Ouvrez Telegram et cherchez [@BotFather](https://t.me/BotFather)
2. Envoyez `/newbot`
3. Choisissez un nom et un username (ex: `mon_serveur_bot`)
4. Copiez le token reçu (ex: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

## Compatibilité

| Composant | Architecture |
|-----------|-------------|
| ZiVPN | Linux x86_64, ARM64 (`aarch64`), ARM 32 bits (`armv7l`) |
| SSH Proxy | Linux (Python asyncio) |
| Bot | Linux, Windows, macOS |

### Serveurs ARM

Les serveurs ARM64 et ARMv7 standards sont pris en charge. `install.sh` détecte automatiquement l'architecture avec `uname -m` et télécharge le binaire ZiVPN adapté :

- `x86_64` : binaire Linux AMD64 ;
- `aarch64` : binaire Linux ARM64 ;
- `armv7l` : binaire Linux ARM 32 bits.

Le reste du projet utilise Python et ne dépend pas d'un binaire spécifique à l'architecture. Le serveur doit utiliser Debian ou Ubuntu, disposer de `sudo`, systemd et d'un accès Internet. Les architectures ARM non listées, comme ARMv6, et les systèmes sans systemd ne sont pas pris en charge automatiquement.

---

*Tags : Telegram Bot, Server Monitoring, ZiVPN Manager, UDP VPN, VPN CRM, SysAdmin, DevOps, Python, Botfather, psutil, Linux Server, Ubuntu VPN Setup, HA Tunnel Plus, HTTP Injector, SSH Payload, SSH Proxy, SNI Spoofing, TCP Custom, SSH Limits, iptables quota, PAM maxlogins, Free Internet Payload.*
