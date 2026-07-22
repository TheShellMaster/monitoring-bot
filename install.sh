#!/bin/bash
# Script d'installation tout-en-un : ZiVPN + Monitoring Bot
# Détecte l'architecture, installe ZiVPN, génère SSL, configure le port UDP 443, et déploie le Bot Telegram.

set -e

echo -e "\e[32m[1] Mise à jour du système et installation des dépendances...\e[0m"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip curl wget openssl jq openssh-server

echo -e "\e[32m[2] Détection de l'architecture...\e[0m"
ARCH=$(uname -m)
case $ARCH in
  x86_64)   ZIP="udp-zivpn-linux-amd64" ;;
  aarch64)  ZIP="udp-zivpn-linux-arm64" ;;
  armv7l)   ZIP="udp-zivpn-linux-arm" ;;
  *)        echo -e "\e[31mArchitecture $ARCH non supportée.\e[0m"; exit 1 ;;
esac

echo -e "\e[32m[3] Installation de ZiVPN ($ARCH)...\e[0m"
sudo systemctl stop zivpn.service 2>/dev/null || true
wget -q "https://github.com/zahidbd2/udp-zivpn/releases/download/udp-zivpn_1.4.9/$ZIP" -O /tmp/zivpn
sudo mv /tmp/zivpn /usr/local/bin/zivpn
sudo chmod +x /usr/local/bin/zivpn
sudo mkdir -p /etc/zivpn

echo -e "\e[32m[4] Génération des certificats SSL...\e[0m"
if [ ! -f "/etc/zivpn/zivpn.crt" ]; then
    sudo openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 \
        -subj "/C=US/ST=CA/L=LA/O=VPN/OU=IT/CN=zivpn" \
        -keyout "/etc/zivpn/zivpn.key" -out "/etc/zivpn/zivpn.crt" 2>/dev/null
fi

echo -e "\e[32m[5] Configuration de ZiVPN (Port 443 UDP, DNS 127.0.0.53)...\e[0m"
sudo tee /etc/zivpn/config.json > /dev/null <<EOF
{
  "listen": ":443",
  "cert": "/etc/zivpn/zivpn.crt",
  "key": "/etc/zivpn/zivpn.key",
  "obfs": "zivpn",
  "resolver": {
    "udp": {
      "addr": "127.0.0.53:53"
    }
  },
  "auth": {
    "mode": "passwords",
    "config": []
  }
}
EOF

sudo sysctl -w net.core.rmem_max=16777216 2>/dev/null || true
sudo sysctl -w net.core.wmem_max=16777216 2>/dev/null || true

sudo tee /etc/systemd/system/zivpn.service > /dev/null <<EOF
[Unit]
Description=ZiVPN UDP Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/etc/zivpn
ExecStart=/usr/local/bin/zivpn server -c /etc/zivpn/config.json
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable zivpn.service
sudo systemctl restart zivpn.service

echo -e "\e[32m[6] Configuration des autorisations (Sudoers)...\e[0m"
USER_CURRENT=$USER
echo "$USER_CURRENT ALL=(ALL) NOPASSWD: /usr/bin/systemctl start zivpn.service, /usr/bin/systemctl stop zivpn.service, /usr/bin/systemctl restart zivpn.service, /usr/bin/systemctl is-active zivpn.service, /usr/bin/systemctl start ssh-proxy.service, /usr/bin/systemctl stop ssh-proxy.service, /usr/bin/systemctl restart ssh-proxy.service, /usr/bin/systemctl is-active ssh-proxy.service, /usr/sbin/useradd, /usr/sbin/userdel, /usr/sbin/usermod, /usr/sbin/chpasswd, /usr/bin/chage, /usr/bin/pkill, /usr/bin/cat /etc/zivpn/config.json, /usr/bin/tee /etc/zivpn/config.json" | sudo tee /etc/sudoers.d/bot-vpn >/dev/null
sudo chmod 440 /etc/sudoers.d/bot-vpn

echo -e "\e[32m[6b] Configuration OpenSSH (sécurisation + autorisation des mots de passe)...\e[0m"
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
# Sur les images cloud AWS/GCP/Azure, un fichier prioritaire peut désactiver les mots de passe - on le corrige
for f in /etc/ssh/sshd_config.d/*.conf; do
    [ -f "$f" ] && sudo sed -i 's/^PasswordAuthentication.*/PasswordAuthentication yes/' "$f"
done
sudo systemctl enable ssh 2>/dev/null || sudo systemctl enable sshd 2>/dev/null || true
sudo systemctl restart ssh 2>/dev/null || sudo systemctl restart sshd 2>/dev/null || true

echo -e "\e[32m[7] Installation du Bot Telegram...\e[0m"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
./venv/bin/pip install -q "python-telegram-bot[job-queue]>=22" psutil requests

read -p "Entrez le token de votre Bot Telegram : " BOT_TOKEN

echo -e "\e[32m[!] Configuration du fuseau horaire...\e[0m"
echo "Veuillez sélectionner votre continent puis votre pays dans les menus suivants :"
TZ_INPUT=$(tzselect)
if [ -z "$TZ_INPUT" ]; then
    TZ_INPUT="Africa/Douala"
fi

echo "TELEGRAM_BOT_TOKEN=$BOT_TOKEN" > .env_bot
echo "TZ=$TZ_INPUT" >> .env_bot

BOT_DIR=$(pwd)
sudo tee /etc/systemd/system/monitoring-bot.service > /dev/null <<EOF
[Unit]
Description=Monitoring Bot Telegram (ZiVPN)
After=network.target

[Service]
Type=simple
User=$USER_CURRENT
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/venv/bin/python3 $BOT_DIR/monitoring-bot.py
Restart=always
RestartSec=10
EnvironmentFile=$BOT_DIR/.env_bot

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable monitoring-bot.service
sudo systemctl restart monitoring-bot.service

echo -e "\e[32m[8] Installation du Proxy SSH Payload (ports 2053 + 8443)...\e[0m"
sudo tee /etc/systemd/system/ssh-proxy.service > /dev/null <<EOF
[Unit]
Description=SSH Payload Proxy (HTTP Injection port 2053 + SSL port 8443)
After=network.target

[Service]
Type=simple
User=$USER_CURRENT
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/venv/bin/python3 $BOT_DIR/ssh_proxy.py
Restart=always
RestartSec=5
EnvironmentFile=$BOT_DIR/.env_bot

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ssh-proxy.service
sudo systemctl restart ssh-proxy.service

PUB_IP=$(curl -s https://api.ipify.org)

echo -e "\e[32m=== ✅ Installation Terminée ! ===\e[0m"
echo -e "IP Serveur          : \e[33m$PUB_IP\e[0m"
echo -e "ZiVPN UDP           : \e[33m443\e[0m"
echo -e "SSH HTTP Injection  : \e[33m2053\e[0m"
echo -e "SSH SSL Passthrough : \e[33m8443\e[0m"
echo -e "Allez sur Telegram et tapez /vpn ou /ssh"
