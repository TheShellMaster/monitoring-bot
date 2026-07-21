import sqlite3
import subprocess
import logging
import os
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

DB_PATH = "vpn_accounts.db"

# Pour tester en local sur le PC (qui n'a pas zivpn ni sudo sans mot de passe),
# on simule les commandes Linux si sudo échoue ou timeout.
MOCK_MODE = not os.path.exists("/etc/zivpn/config.json")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS vpn_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            duration_days INTEGER,
            data_limit_gb REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def add_user(username, password, duration_days, data_limit_gb):
    expires_at = datetime.now() + timedelta(days=duration_days)
    exp_str = expires_at.strftime("%Y-%m-%d")
    
    try:
        if MOCK_MODE:
            log.info(f"[MOCK] useradd -M -s /bin/false {username}")
            log.info(f"[MOCK] echo {username}:{password} | chpasswd")
            log.info(f"[MOCK] chage -E {exp_str} {username}")
        else:
            # 1. Linux user creation
            subprocess.run(["sudo", "useradd", "-M", "-s", "/bin/false", username], check=True, timeout=5)
            # 2. Set password
            proc = subprocess.Popen(["sudo", "chpasswd"], stdin=subprocess.PIPE, text=True)
            proc.communicate(f"{username}:{password}", timeout=5)
            if proc.returncode != 0:
                raise Exception("Failed to set password")
            # 3. Set expiration
            subprocess.run(["sudo", "chage", "-E", exp_str, username], check=True, timeout=5)
            
        # 4. Save to DB
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO vpn_users (username, password, duration_days, data_limit_gb, expires_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (username, password, duration_days, data_limit_gb, expires_at.strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        return True, "Compte cree avec succes."
    except Exception as e:
        log.error(f"Error adding user: {e}")
        if not MOCK_MODE:
            subprocess.run(["sudo", "userdel", "-r", username], stderr=subprocess.DEVNULL, timeout=5)
        return False, f"Erreur : {e} (Mode test local ?)"

def del_user(username):
    try:
        if MOCK_MODE:
            log.info(f"[MOCK] userdel -r {username}")
        else:
            subprocess.run(["sudo", "userdel", "-r", username], check=True, timeout=5)
            
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('DELETE FROM vpn_users WHERE username = ?', (username,))
        conn.commit()
        conn.close()
        return True, "Compte supprime."
    except Exception as e:
        log.error(f"Error deleting user: {e}")
        return False, str(e)

def list_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT username, password, expires_at, data_limit_gb FROM vpn_users')
    rows = c.fetchall()
    conn.close()
    return rows

_mock_status = True

def zivpn_action(action):
    # action: "start" or "stop"
    global _mock_status
    try:
        if MOCK_MODE:
            log.info(f"[MOCK] systemctl {action} zivpn.service")
            _mock_status = (action == "start")
            return True, f"Service zivpn {action}ed (SIMULÉ)."
        else:
            subprocess.run(["sudo", "-n", "systemctl", action, "zivpn.service"], check=True, timeout=5)
            return True, f"Service zivpn {action}ed."
    except Exception as e:
        return False, f"Interdit en local sans mot de passe : {e}"

def check_zivpn_status():
    if MOCK_MODE:
        return _mock_status
    try:
        r = subprocess.run(["sudo", "-n", "systemctl", "is-active", "zivpn.service"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except:
        return False
