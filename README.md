# Monitoring Bot & ZiVPN Manager 🛡️

Bot Telegram tout-en-un pour surveiller votre serveur Linux en temps réel et gérer un serveur VPN (ZiVPN UDP) via une interface Telegram interactive.

## Fonctionnalités Principales

### 📈 Monitoring Serveur
| Commande | Description |
|----------|-------------|
| `/status` | Tableau de bord complet (CPU, RAM, disque, réseau, uptime) |
| `/system` | Informations système (OS, kernel, arch, boot) |
| `/cpu` | Utilisation CPU, charge, fréquence, cœurs |
| `/ram` | RAM et Swap (total, utilisé, libre) |
| `/disk` | Disque et entrées/sorties |
| `/network` | Statistiques réseau par interface |
| `/gpu` | GPU NVIDIA (usage, VRAM, température) |

**Alertes automatiques** : Le bot vous notifie automatiquement si CPU > 80%, RAM > 85%, ou Disque > 85%.

### 🔐 Gestionnaire ZiVPN (UDP)
La commande `/vpn` ouvre un CRM interactif complet pour votre serveur VPN :
- **Serveur ZiVPN** : Démarrer / Stopper le service système `zivpn` depuis Telegram.
- **Créer des accès** : Demande interactive (Utilisateur > Mot de passe > Date et Heure d'expiration).
- **Modification Complète** : Changer le mot de passe ou l'expiration (précision à la minute près `YYYY-MM-DD HH:MM`) à tout moment.
- **Suppression/Verrouillage** : Un clic pour bannir un utilisateur et couper sa connexion (`pkill`).
- **Synchronisation** : Mise à jour automatique de `/etc/zivpn/config.json`.

---

## 🚀 Installation "All-In-One" (Recommandé)

Un script automatique installe et configure **absolument tout** pour vous (détection CPU, téléchargement de ZiVPN, certificats SSL, configuration du port UDP 443, et installation du bot Telegram) !

Exécutez ces 3 lignes sur un serveur Ubuntu/Debian vierge :

```bash
git clone https://github.com/TheShellMaster/monitoring-bot.git
cd monitoring-bot
sudo bash install.sh
```

*(Le script vous demandera uniquement votre Token Telegram).*

---

## ⚙️ Installation Manuelle

Si vous préférez installer manuellement (sans le serveur ZiVPN inclus) :

```bash
git clone https://github.com/TheShellMaster/monitoring-bot.git
cd monitoring-bot
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
echo "TELEGRAM_BOT_TOKEN=votre_token_ici" > .env_bot
./venv/bin/python3 monitoring-bot.py
```

## Obtenir un token Telegram
1. Ouvrez Telegram et cherchez [@BotFather](https://t.me/BotFather)
2. Envoyez `/newbot`
3. Choisissez un nom et un username (ex: `mon_serveur_bot`)
4. Copiez le token reçu (ex: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

## Compatibilité

| Composant | Statut |
|------------|--------|
| ZiVPN Serveur | Linux x86_64, ARM64, ARM |
| Bot Python | Windows, macOS, Linux |

---
*Tags pour Google et GitHub SEO: Telegram Bot, Server Monitoring, ZiVPN Manager, UDP VPN, VPN CRM, SysAdmin, DevOps, Python, Botfather, psutil, Linux Server, Ubuntu VPN Setup.*
