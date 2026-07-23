#!/bin/bash
# Installation tout-en-un : ZiVPN (UDP 443) + SSH Payload Proxy (2053/8443) + Bot Telegram
# Detecte l'architecture, installe les binaires, configure les services systemd.
# Usage: sudo bash install.sh  (ou en tant que user sudo)

ERR=0
step()  { echo -e "\e[32m[$1/$2] $3...\e[0m"; }
err()   { echo -e "\e[31mERREUR: $1\e[0m"; ERR=1; }
warn()  { echo -e "\e[33mATTENTION: $1\e[0m"; }

# ── Vérification user ──
if [ "$(id -u)" = "0" ]; then
    USER_DETECTED=$(logname 2>/dev/null || echo "root")
else
    USER_DETECTED=$USER
fi
echo ""
echo -e "\e[32m[!] Configuration de l'utilisateur systeme...\e[0m"
echo "Utilisateur systeme detecte : $USER_DETECTED"
read -p "Nom d'utilisateur pour les services (Entree = $USER_DETECTED) : " USER_INPUT
USER_CURRENT="${USER_INPUT:-$USER_DETECTED}"
BOT_DIR=$(pwd)

# ── [1] Dépendances système ──
step 1 9 "Mise à jour et installation des dépendances"
sudo apt-get update || err "apt update"
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-venv python3-pip curl wget openssl jq openssh-server \
    iptables iptables-persistent tzdata || err "apt install"
warn "Les regles iptables-persistent seront sauvegardees a la fin."

# ── [2] Architecture ──
step 2 9 "Détection de l'architecture"
ARCH=$(uname -m)
case $ARCH in
  x86_64)  ZIP="udp-zivpn-linux-amd64"  ;;
  aarch64) ZIP="udp-zivpn-linux-arm64"  ;;
  armv7l)  ZIP="udp-zivpn-linux-arm"    ;;
  *)       err "Architecture $ARCH non supportée."; exit 1 ;;
esac
echo "  -> $ARCH"

# ── [3] ZiVPN ──
step 3 9 "Installation de ZiVPN ($ARCH)"
sudo systemctl stop zivpn.service 2>/dev/null || true
wget -q "https://github.com/zahidbd2/udp-zivpn/releases/download/udp-zivpn_1.4.9/$ZIP" -O /tmp/zivpn
if [ ! -s /tmp/zivpn ]; then
    err "Echec du téléchargement de ZiVPN"
    exit 1
fi
sudo mv /tmp/zivpn /usr/local/bin/zivpn
sudo chmod +x /usr/local/bin/zivpn
sudo mkdir -p /etc/zivpn

# ── [4] Certificats SSL ──
step 4 9 "Génération des certificats SSL"
if [ ! -f "/etc/zivpn/zivpn.crt" ]; then
    sudo openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 \
        -subj "/C=US/ST=CA/L=LA/O=VPN/OU=IT/CN=zivpn" \
        -keyout "/etc/zivpn/zivpn.key" -out "/etc/zivpn/zivpn.crt" 2>/dev/null
    echo "  -> Certificats créés"
else
    echo "  -> Déjà existants, on garde"
fi

# ── [5] Configuration ZiVPN + service systemd ──
step 5 9 "Configuration ZiVPN (Port 443 UDP)"
sudo tee /etc/zivpn/config.json > /dev/null <<EOF
{
  "listen": ":443",
  "cert": "/etc/zivpn/zivpn.crt",
  "key": "/etc/zivpn/zivpn.key",
  "obfs": "zivpn",
  "resolver": { "udp": { "addr": "127.0.0.53:53" } },
  "auth": { "mode": "passwords", "config": [] }
}
EOF

sudo sysctl -w net.core.rmem_max=16777216 >/dev/null
sudo sysctl -w net.core.wmem_max=16777216 >/dev/null
# Rendre persistants
echo "net.core.rmem_max=16777216" | sudo tee /etc/sysctl.d/99-zivpn.conf >/dev/null
echo "net.core.wmem_max=16777216" | sudo tee -a /etc/sysctl.d/99-zivpn.conf >/dev/null

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
sudo systemctl restart zivpn.service && echo "  -> ZiVPN actif"

# ── [6] Sudoers ──
step 6 9 "Configuration des permissions sudoers"
SUDOERS_LINE="$USER_CURRENT ALL=(ALL) NOPASSWD: \
  /usr/bin/systemctl start zivpn.service, \
  /usr/bin/systemctl stop zivpn.service, \
  /usr/bin/systemctl restart zivpn.service, \
  /usr/bin/systemctl is-active zivpn.service, \
  /usr/bin/systemctl start ssh-proxy.service, \
  /usr/bin/systemctl stop ssh-proxy.service, \
  /usr/bin/systemctl restart ssh-proxy.service, \
  /usr/bin/systemctl is-active ssh-proxy.service, \
  /usr/sbin/useradd, /usr/sbin/userdel, /usr/sbin/usermod, \
  /usr/sbin/chpasswd, /usr/bin/chage, /usr/bin/pkill, \
  /usr/bin/cat /etc/zivpn/config.json, /usr/bin/tee /etc/zivpn/config.json, \
  /usr/bin/tee /etc/security/limits.conf, /usr/bin/sed, \
  /usr/sbin/iptables, /sbin/iptables"
echo "$SUDOERS_LINE" | sudo tee /etc/sudoers.d/bot-vpn >/dev/null
sudo chmod 440 /etc/sudoers.d/bot-vpn

# ── [6b] OpenSSH ──
step 6b 9 "Configuration OpenSSH (PasswordAuthentication)"
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
for f in /etc/ssh/sshd_config.d/*.conf; do
    [ -f "$f" ] && sudo sed -i 's/^PasswordAuthentication.*/PasswordAuthentication yes/' "$f"
done
sudo systemctl enable ssh 2>/dev/null || sudo systemctl enable sshd 2>/dev/null || true
sudo systemctl restart ssh 2>/dev/null || sudo systemctl restart sshd 2>/dev/null || true

# ── [7] Firewall : ouvrir les ports ──
step 7 9 "Ouverture des ports (firewall)"
if command -v ufw &>/dev/null && ufw status | grep -q "active"; then
    sudo ufw allow 443/udp  comment "ZiVPN"
    sudo ufw allow 2053/tcp comment "SSH HTTP Injection"
    sudo ufw allow 8443/tcp comment "SSH SSL Passthrough"
    sudo ufw reload
    echo "  -> Ports ouverts sur ufw"
elif command -v firewall-cmd &>/dev/null; then
    sudo firewall-cmd --permanent --add-port=443/udp
    sudo firewall-cmd --permanent --add-port=2053/tcp
    sudo firewall-cmd --permanent --add-port=8443/tcp
    sudo firewall-cmd --reload
    echo "  -> Ports ouverts sur firewalld"
else
    # Fallback iptables direct
    sudo iptables -A INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null || true
    sudo iptables -A INPUT -p tcp --dport 2053 -j ACCEPT 2>/dev/null || true
    sudo iptables -A INPUT -p tcp --dport 8443 -j ACCEPT 2>/dev/null || true
    echo "  -> Regles iptables ajoutees"
fi

# ── [8] Bot Telegram ──
step 8 9 "Installation du Bot Telegram"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
if [ -f "requirements.txt" ]; then
    ./venv/bin/pip install -q -r requirements.txt
else
    ./venv/bin/pip install -q "python-telegram-bot[job-queue]>=22" psutil
fi

# Token Telegram
while true; do
    read -p "Entrez le token de votre Bot Telegram (@BotFather) : " BOT_TOKEN
    [ -z "$BOT_TOKEN" ] && echo "Token requis." && continue
    RESP=$(curl -s "https://api.telegram.org/bot$BOT_TOKEN/getMe")
    if echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)" 2>/dev/null; then
        BOT_NAME=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['username'])")
        echo "  -> Token valide ! Bot: @$BOT_NAME"
        break
    else
        echo "  -> Token invalide. Reessaye."
    fi
done

# Fuseau horaire
echo -e "\e[32m[!] Configuration du fuseau horaire...\e[0m"
echo "Selectionne ton continent puis ton pays dans les menus :"
TZ_INPUT=$(tzselect 2>/dev/null || echo "")
if [ -z "$TZ_INPUT" ]; then
    TZ_INPUT="Africa/Douala"
    echo "  -> Defaut: $TZ_INPUT"
fi

echo "TELEGRAM_BOT_TOKEN=$BOT_TOKEN" > .env_bot
echo "TZ=$TZ_INPUT" >> .env_bot

# ID Admin Telegram
echo ""
echo -e "\e[32m[!] Configuration de l'administrateur...\e[0m"
echo "Pour trouver ton ID Telegram :"
echo "  1. Envoie /start a ton bot"
echo "  2. Va sur https://api.telegram.org/bot${BOT_TOKEN}/getUpdates"
echo "  3. Cherche 'chat':{\"id\": TON_ID} dans la reponse JSON"
echo ""
read -p "Colle ton ID Telegram (ou appuie sur Entree pour plus tard) : " ADMIN_ID
if [ -n "$ADMIN_ID" ]; then
    echo "ADMIN_CHAT_ID=$ADMIN_ID" >> .env_bot
    echo "  -> Admin configure"
else
    echo "  -> Tu pourras ajouter ADMIN_CHAT_ID dans .env_bot plus tard"
fi

# Service monitoring-bot
sudo tee /etc/systemd/system/monitoring-bot.service > /dev/null <<EOF
[Unit]
Description=Monitoring Bot Telegram (ZiVPN + SSH)
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
sudo systemctl restart monitoring-bot.service && echo "  -> Bot actif"

# ── [9] Proxy SSH Payload ──
step 9 9 "Installation du Proxy SSH Payload (2053 + 8443)"
sudo tee /etc/systemd/system/ssh-proxy.service > /dev/null <<EOF
[Unit]
Description=SSH Payload Proxy (HTTP Injection 2053 + SSL 8443)
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
sudo systemctl restart ssh-proxy.service && echo "  -> Proxy SSH actif"

# ── Sauvegarde iptables ──
echo -e "\e[32m[!] Sauvegarde des regles iptables...\e[0m"
sudo iptables-save | sudo tee /etc/iptables/rules.v4 > /dev/null 2>&1 || \
    warn "Impossible de sauvegarder iptables (pas de iptables-persistent?)"

# ── Résumé ──
PUB_IP=$(curl -s https://api.ipify.org 2>/dev/null || echo "IP inconnue")
echo ""
echo -e "\e[32m========================================\e[0m"
echo -e "\e[32m  ✅ Installation Terminée\e[0m"
echo -e "\e[32m========================================\e[0m"
echo -e "  \e[33mIP Serveur   :\e[0m $PUB_IP"
echo -e "  \e[33mZiVPN UDP    :\e[0m port 443"
echo -e "  \e[33mSSH HTTP Inj :\e[0m port 2053"
echo -e "  \e[33mSSH SSL      :\e[0m port 8443"
echo -e "  \e[33mFuseau       :\e[0m $TZ_INPUT"
echo -e "  \e[33mBot          :\e[0m @$BOT_NAME"
echo ""
echo -e "  Va sur Telegram et tape /start"
echo -e "  Puis /vpn pour gerer les comptes VPN"
echo -e "  Puis /ssh pour gerer les comptes SSH Payload"
echo ""

if [ "$ERR" = "1" ]; then
    warn "Certaines etapes ont echoue, verifie les logs ci-dessus."
fi
