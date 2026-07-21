# Monitoring Bot

Bot Telegram de surveillance matérielle en temps réel pour serveur Linux.

## Fonctionnalités

| Commande | Description |
|----------|-------------|
| `/status` | Tableau de bord complet (CPU, RAM, disque, réseau, uptime) |
| `/system` | Informations système (OS, kernel, arch, boot) |
| `/cpu` | Utilisation CPU, charge, fréquence, cœurs |
| `/ram` | RAM et Swap (total, utilisé, libre) |
| `/disk` | Disque et entrées/sorties |
| `/gpu` | GPU NVIDIA (usage, VRAM, température) |
| `/network` | Statistiques réseau par interface (trafic, erreurs, débit) |
| `/help` | Aide et liste des commandes |

**Alertes automatiques** : CPU > 80%, RAM > 85%, Disque > 85%

## Installation

```bash
# Cloner le dépôt
git clone https://github.com/votre-utilisateur/monitoring-bot.git
cd monitoring-bot

# Installer les dépendances
pip install -r requirements.txt

# Configurer le token Telegram
echo "TELEGRAM_BOT_TOKEN=votre_token_ici" > .env_bot

# Lancer le bot
python3 monitoring-bot.py
```

### Service systemd (optionnel)

```bash
sudo cat > /etc/systemd/system/monitoring-bot.service << EOF
[Unit]
Description=Monitoring Bot Telegram
After=network.target

[Service]
Type=simple
User=votre_user
WorkingDirectory=/chemin/vers/monitoring-bot
ExecStart=/usr/bin/python3 /chemin/vers/monitoring-bot/monitoring-bot.py
Restart=always
RestartSec=10
EnvironmentFile=/chemin/vers/monitoring-bot/.env_bot

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now monitoring-bot
```

## Obtenir un token Telegram

1. Ouvrir Telegram et chercher [@BotFather](https://t.me/BotFather)
2. Envoyer `/newbot`
3. Choisir un nom (ex: `Mon Serveur`)
4. Choisir un username (ex: `mon_serveur_bot`)
5. Copier le token reçu

## Compatibilité

| Plateforme | Statut |
|------------|--------|
| Linux x86_64 | ✅ |
| Linux ARM64 (RPi, AWS Graviton) | ✅ |
| Linux ARM (Raspberry Pi) | ✅ |
| macOS Intel | ✅ |
| macOS Apple Silicon | ✅ |
| Windows | ✅ |

Le bot détecte automatiquement le matériel disponible. La commande `/gpu` nécessite un GPU NVIDIA avec `nvidia-smi`.

## Dépendances

- Python 3.8+
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- [psutil](https://github.com/giampaolo/psutil)
