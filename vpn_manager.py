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


_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("VPN_DB_PATH", os.path.join(_DIR, "vpn_accounts.db"))
ZIVPN_CONF = "/etc/zivpn/config.json"
VPN_GROUP = os.getenv("VPN_USERS_GROUP", "vpnusers")
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        )
    ''')
    try:
        c.execute("ALTER TABLE vpn_users ADD COLUMN locked INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()
    _sync_vpn_group_members()
    _sync_system_users()

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

def _db_user_exists(username):
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("SELECT 1 FROM vpn_users WHERE username=?", (username,))
        return c.fetchone() is not None
    finally:
        conn.close()

def _sudo_run(cmd, check=True):
    if MOCK_MODE:
        log.info(f"[MOCK] {' '.join(cmd)}")
        return True
    try:
        subprocess.run(cmd, check=check, timeout=5)
        return True
    except Exception as e:
        log.error(f"Error running command {cmd}: {e}")
        return False

def _ensure_group():
    try:
        r = subprocess.run(["getent", "group", VPN_GROUP], capture_output=True, timeout=5)
        if r.returncode == 0:
            return True
    except Exception:
        pass
    return _sudo_run(["sudo", "-n", "groupadd", "-f", VPN_GROUP])

def _add_to_vpn_group(username):
    if not _ensure_group():
        return False
    return _sudo_run(["sudo", "-n", "usermod", "-aG", VPN_GROUP, username])

def _group_members():
    try:
        result = subprocess.run(
            ["getent", "group", VPN_GROUP], capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return set()
        fields = result.stdout.strip().split(":")
        return {name for name in fields[3].split(",") if name} if len(fields) > 3 else set()
    except Exception:
        return set()

def _remove_from_vpn_group(username):
    if MOCK_MODE:
        return True
    return _sudo_run(["sudo", "-n", "gpasswd", "-d", username, VPN_GROUP])

def _sync_vpn_group_members():
    try:
        _ensure_group()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT username FROM vpn_users WHERE locked=0")
        users = [row[0] for row in c.fetchall()]
        conn.close()
        active_users = {username for username in users if _user_exists(username)}
        for username in active_users:
            _add_to_vpn_group(username)
        for username in _group_members() - active_users:
            _remove_from_vpn_group(username)
    except Exception as e:
        log.error(f"Error syncing VPN group: {e}")

def _ssh_db_user_exists(username):
    ssh_db_path = os.getenv("SSH_DB_PATH", os.path.join(_DIR, "ssh_accounts.db"))
    if not os.path.exists(ssh_db_path):
        return False
    conn = sqlite3.connect(ssh_db_path)
    try:
        c = conn.cursor()
        c.execute("SELECT 1 FROM ssh_users WHERE username=?", (username,))
        return c.fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()

def _get_vpn_group_users():
    try:
        r = subprocess.run(["getent", "group", VPN_GROUP], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return []
        parts = r.stdout.strip().split(":")
        if len(parts) < 4 or not parts[3]:
            return []
        return [u.strip() for u in parts[3].split(",") if u.strip()]
    except Exception:
        return []

def _system_expiry(username):
    if MOCK_MODE:
        return "2099-12-31 23:59:00"
    try:
        r = subprocess.run(["sudo", "-n", "chage", "-l", username], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.startswith("Account expires"):
                raw = line.split(":", 1)[1].strip()
                if raw.lower() == "never":
                    return "2099-12-31 23:59:00"
                for fmt in ("%b %d, %Y", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(raw, fmt).strftime("%Y-%m-%d 23:59:00")
                    except ValueError:
                        pass
    except Exception as e:
        log.error(f"Error reading expiry for {username}: {e}")
    return "2099-12-31 23:59:00"

def _sync_system_users():
    """Réimporte les comptes ZiVPN système absents de la DB.

    On ignore les utilisateurs déjà présents dans ssh_accounts.db pour éviter
    de mélanger les deux CRM si une ancienne installation partageait le groupe.
    """
    for username in _get_vpn_group_users():
        username = username.strip().lower()
        if not username or _db_user_exists(username) or _ssh_db_user_exists(username):
            continue
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute(
                "INSERT INTO vpn_users (username, password, expires_at) VALUES (?, ?, ?)",
                (username, "inconnu", _system_expiry(username)),
            )
            conn.commit()
            conn.close()
            _update_zivpn_config(username, "add")
            log.info(f"Synced existing ZiVPN user {username} into DB")
        except sqlite3.IntegrityError:
            pass
        except Exception as e:
            log.error(f"Error syncing ZiVPN user {username}: {e}")

def add_user(username, password, expires_at_str):
    username = username.strip().lower()
    try:
        expires_at = datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M")
    except:
        return False, "Format de date invalide."

    if _db_user_exists(username):
        return False, f"Le compte ZiVPN {username} existe deja dans la base."
    if not MOCK_MODE and _user_exists(username):
        return False, (
            f"L'utilisateur Linux {username} existe deja. "
            "Choisis un autre nom ou supprime d'abord le compte existant."
        )
    
    exp_str = expires_at.strftime("%Y-%m-%d")
    created_system_user = False
    
    try:
        if MOCK_MODE:
            log.info(f"[MOCK] useradd -M -s /bin/false {username}")
        else:
            subprocess.run(["sudo", "useradd", "-M", "-s", "/bin/false", username], check=True, timeout=5)
            created_system_user = True
            proc = subprocess.Popen(["sudo", "chpasswd"], stdin=subprocess.PIPE, text=True)
            proc.communicate(f"{username}:{password}", timeout=5)
            if proc.returncode != 0: raise Exception("Failed to set password")
            subprocess.run(["sudo", "chage", "-E", exp_str, username], check=True, timeout=5)
            if not _add_to_vpn_group(username):
                raise Exception(f"Failed to add user to {VPN_GROUP}")
            
        if not _update_zivpn_config(username, "add"):
            raise Exception("Impossible de mettre a jour la configuration ZiVPN")
            
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO vpn_users (username, password, expires_at)
            VALUES (?, ?, ?)
        ''', (username, password, expires_at.strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        return True, "Compte cree avec succes."
    except Exception as e:
        log.error(f"Error adding user: {e}")
        if created_system_user:
            subprocess.run(["sudo", "userdel", "-r", username], stderr=subprocess.DEVNULL, timeout=5)
        return False, str(e)

def del_user(username):
    try:
        if not MOCK_MODE:
            subprocess.run(["sudo", "userdel", "-r", username], check=False, timeout=5)
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
        if not MOCK_MODE and _user_exists(username):
            subprocess.run(["sudo", "usermod", "-L", username], check=False, timeout=5)
            subprocess.run(["sudo", "pkill", "-u", username], stderr=subprocess.DEVNULL)
        _update_zivpn_config(username, "del")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE vpn_users SET locked=1 WHERE username=?", (username,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.error(f"Error locking user: {e}")
        return False

def _user_exists(username):
    try:
        subprocess.run(["id", username], check=True, capture_output=True, timeout=5)
        return True
    except:
        return False

def unlock_user(username):
    try:
        if not MOCK_MODE and _user_exists(username):
            subprocess.run(["sudo", "usermod", "-U", username], check=True, timeout=5)
        _update_zivpn_config(username, "add")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE vpn_users SET locked=0 WHERE username=?", (username,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.error(f"Error unlocking user: {e}")
        return False

def list_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT username, password, expires_at FROM vpn_users')
    rows = c.fetchall()
    conn.close()
    return rows

def get_user(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT username, password, expires_at FROM vpn_users WHERE username=?', (username,))
    row = c.fetchone()
    conn.close()
    return row

def update_user_field(username, field, value):
    try:
        if field == "password":
            if not MOCK_MODE and _user_exists(username):
                proc = subprocess.Popen(["sudo", "chpasswd"], stdin=subprocess.PIPE, text=True)
                proc.communicate(f"{username}:{value}", timeout=5)
                if proc.returncode != 0: raise Exception("Failed to set password")
            col = "password"
        elif field == "expires_at":
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
            if not MOCK_MODE and _user_exists(username):
                subprocess.run(["sudo", "chage", "-E", dt.strftime("%Y-%m-%d"), username], check=True, timeout=5)
            if dt.replace(tzinfo=TZ) > _now():
                unlock_user(username)
            col = "expires_at"
            value = dt.strftime("%Y-%m-%d %H:%M:%S")
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
    c.execute('SELECT username FROM vpn_users WHERE expires_at <= ? AND locked=0', (now,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]
