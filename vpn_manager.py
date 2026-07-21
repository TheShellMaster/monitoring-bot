import sqlite3
import subprocess
import logging
import os
import json
import zoneinfo
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# Configurable Timezone (Défaut : Africa/Douala)
TZ = zoneinfo.ZoneInfo(os.getenv("TZ", "Africa/Douala"))

def _now():
    return datetime.now(TZ)


DB_PATH = "vpn_accounts.db"
ZIVPN_CONF = "/etc/zivpn/config.json"
MOCK_MODE = not os.path.exists(ZIVPN_CONF)

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

def _update_zivpn_config(username, action="add"):
    if MOCK_MODE:
        log.info(f"[MOCK] Zivpn config {action} user {username}")
        return True
    
    try:
        # We need to use sudo to read and write the config file
        res = subprocess.run(["sudo", "cat", ZIVPN_CONF], capture_output=True, text=True, check=True)
        config = json.loads(res.stdout)
        
        users = config.get("auth", {}).get("config", [])
        if action == "add" and username not in users:
            users.append(username)
        elif action == "del" and username in users:
            users.remove(username)
            
        config["auth"]["config"] = users
        
        # Write back
        new_conf = json.dumps(config, indent=2)
        proc = subprocess.Popen(["sudo", "tee", ZIVPN_CONF], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
        proc.communicate(new_conf)
        
        # Restart zivpn to apply changes
        subprocess.run(["sudo", "systemctl", "restart", "zivpn.service"], check=True)
        return True
    except Exception as e:
        log.error(f"Error updating zivpn config: {e}")
        return False

def add_user(username, password, expires_at_str, data_limit_gb):
    try:
        expires_at = datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M")
    except:
        return False, "Format de date invalide."
    
    exp_str = expires_at.strftime("%Y-%m-%d")
    
    try:
        if MOCK_MODE:
            log.info(f"[MOCK] useradd -M -s /bin/false {username}")
        else:
            subprocess.run(["sudo", "useradd", "-M", "-s", "/bin/false", username], check=True, timeout=5)
            proc = subprocess.Popen(["sudo", "chpasswd"], stdin=subprocess.PIPE, text=True)
            proc.communicate(f"{username}:{password}", timeout=5)
            if proc.returncode != 0: raise Exception("Failed to set password")
            subprocess.run(["sudo", "chage", "-E", exp_str, username], check=True, timeout=5)
            
        _update_zivpn_config(username, "add")
            
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO vpn_users (username, password, duration_days, data_limit_gb, expires_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (username, password, duration_hours, data_limit_gb, expires_at.strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        return True, "Compte cree avec succes."
    except Exception as e:
        log.error(f"Error adding user: {e}")
        if not MOCK_MODE:
            subprocess.run(["sudo", "userdel", "-r", username], stderr=subprocess.DEVNULL, timeout=5)
        return False, str(e)

def del_user(username):
    try:
        if not MOCK_MODE:
            subprocess.run(["sudo", "userdel", "-r", username], check=True, timeout=5)
            subprocess.run(["sudo", "pkill", "-u", username], stderr=subprocess.DEVNULL)
            
        _update_zivpn_config(username, "del")
            
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('DELETE FROM vpn_users WHERE username = ?', (username,))
        conn.commit()
        conn.close()
        return True, "Compte supprime."
    except Exception as e:
        log.error(f"Error deleting user: {e}")
        return False, str(e)

def lock_user(username):
    try:
        if not MOCK_MODE:
            subprocess.run(["sudo", "usermod", "-L", username], check=True, timeout=5)
            subprocess.run(["sudo", "pkill", "-u", username], stderr=subprocess.DEVNULL)
        _update_zivpn_config(username, "del")
        return True
    except Exception as e:
        log.error(f"Error locking user: {e}")
        return False

def unlock_user(username):
    try:
        if not MOCK_MODE:
            subprocess.run(["sudo", "usermod", "-U", username], check=True, timeout=5)
        _update_zivpn_config(username, "add")
        return True
    except Exception as e:
        log.error(f"Error unlocking user: {e}")
        return False

def list_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT username, password, expires_at, data_limit_gb FROM vpn_users')
    rows = c.fetchall()
    conn.close()
    return rows

def get_user(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT username, password, expires_at, data_limit_gb FROM vpn_users WHERE username=?', (username,))
    row = c.fetchone()
    conn.close()
    return row

def update_user_field(username, field, value):
    try:
        if field == "password":
            if not MOCK_MODE:
                proc = subprocess.Popen(["sudo", "chpasswd"], stdin=subprocess.PIPE, text=True)
                proc.communicate(f"{username}:{value}", timeout=5)
                if proc.returncode != 0: raise Exception("Failed to set password")
            col = "password"
        elif field == "expires_at":
            # value should be "YYYY-MM-DD HH:MM"
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
            if not MOCK_MODE:
                subprocess.run(["sudo", "chage", "-E", dt.strftime("%Y-%m-%d"), username], check=True, timeout=5)
            
            # If the new date is in the future, unlock the user
            if dt.replace(tzinfo=TZ) > _now():
                unlock_user(username)
                
            col = "expires_at"
            value = dt.strftime("%Y-%m-%d %H:%M:%S")
        elif field == "data_limit_gb":
            col = "data_limit_gb"
        else:
            return False, "Champ inconnu"
            
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(f'UPDATE vpn_users SET {col}=? WHERE username=?', (value, username))
        conn.commit()
        conn.close()
        return True, "Mise a jour reussie."
    except Exception as e:
        return False, str(e)

_mock_status = True
def zivpn_action(action):
    global _mock_status
    try:
        if MOCK_MODE:
            _mock_status = (action == "start")
            return True, f"Service zivpn {action}ed (SIMULÉ)."
        else:
            subprocess.run(["sudo", "-n", "systemctl", action, "zivpn.service"], check=True, timeout=5)
            return True, f"Service zivpn {action}ed."
    except Exception as e:
        return False, str(e)

def check_zivpn_status():
    if MOCK_MODE: return _mock_status
    try:
        r = subprocess.run(["sudo", "-n", "systemctl", "is-active", "zivpn.service"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except:
        return False

def get_expired_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = _now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('SELECT username FROM vpn_users WHERE expires_at <= ?', (now,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]
