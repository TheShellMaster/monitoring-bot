"""
ssh_manager.py - Gestionnaire des comptes SSH
Base de données : ssh_accounts.db  (SÉPARÉE de vpn_accounts.db)
NE PAS MÉLANGER avec vpn_manager.py
"""
import sqlite3
import subprocess
import logging
import os
import shutil
import pwd
import zoneinfo
from datetime import datetime

log = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("SSH_DB_PATH", os.path.join(_DIR, "ssh_accounts.db"))
LIMITS_CONF = "/etc/security/limits.conf"
SSH_GROUP = os.getenv("SSH_USERS_GROUP", "sshusers")
TZ = zoneinfo.ZoneInfo(os.getenv("TZ", "Africa/Douala"))

MOCK_MODE = False


def _now():
    return datetime.now(TZ)


def _run(cmd, check=True, **kwargs):
    """Lance une commande sudo. En mode mock, logue seulement."""
    if MOCK_MODE:
        log.info(f"[MOCK SSH] {' '.join(cmd)}")
        return True
    try:
        subprocess.run(cmd, check=check, timeout=5, **kwargs)
        return True
    except Exception as e:
        log.error(f"Erreur commande SSH {cmd}: {e}")
        return False

def _ensure_group():
    if MOCK_MODE:
        return True
    try:
        r = subprocess.run(["getent", "group", SSH_GROUP], capture_output=True, timeout=5)
        if r.returncode == 0:
            return True
    except Exception:
        pass
    return _run(["sudo", "-n", "groupadd", "-f", SSH_GROUP])

def _add_to_ssh_group(username):
    if MOCK_MODE:
        return True
    if not _ensure_group():
        return False
    return _run(["sudo", "-n", "usermod", "-aG", SSH_GROUP, username])

def _group_members():
    try:
        result = subprocess.run(
            ["getent", "group", SSH_GROUP], capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return set()
        fields = result.stdout.strip().split(":")
        return {name for name in fields[3].split(",") if name} if len(fields) > 3 else set()
    except Exception:
        return set()

def _remove_from_ssh_group(username):
    if MOCK_MODE:
        return True
    return _run(["sudo", "-n", "gpasswd", "-d", username, SSH_GROUP])

def _sync_ssh_group_members():
    if MOCK_MODE:
        return
    try:
        _ensure_group()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT username FROM ssh_users WHERE locked=0")
        users = [row[0] for row in c.fetchall()]
        conn.close()
        active_users = {username for username in users if _user_exists(username)}
        for username in active_users:
            _add_to_ssh_group(username)
        for username in _group_members() - active_users:
            _remove_from_ssh_group(username)
    except Exception as e:
        log.error(f"Erreur sync groupe SSH: {e}")


# ──────────── Helpers limites connexion (PAM) ────────────

def _limits_conf_add(username, max_conn):
    if max_conn <= 0:
        return True
    _limits_conf_remove(username)
    entry = f"{username} hard maxlogins {max_conn}"
    if MOCK_MODE:
        log.info(f"[MOCK SSH] limits.conf: {entry}")
        return True
    try:
        proc = subprocess.Popen(["sudo", "tee", "-a", LIMITS_CONF], stdin=subprocess.PIPE, text=True)
        proc.communicate(entry + "\n", timeout=5)
        return True
    except Exception as e:
        log.error(f"Erreur limits.conf: {e}")
        return False

def _limits_conf_remove(username):
    if MOCK_MODE:
        return True
    try:
        subprocess.run(["sudo", "sed", "-i", f"/^{username}.*maxlogins/d", LIMITS_CONF],
                       check=False, timeout=5)
        return True
    except Exception as e:
        log.error(f"Erreur nettoyage limits.conf: {e}")
        return False

# ──────────── Helpers quota data (iptables) ────────────

def _get_uid(username):
    try:
        return pwd.getpwnam(username).pw_uid
    except KeyError:
        return None

def _iptables_add(username):
    if MOCK_MODE:
        log.info(f"[MOCK SSH] iptables add rules for {username}")
        return True
    uid = _get_uid(username)
    if uid is None:
        return False
    ok = True
    for chain in ["OUTPUT"]:
        try:
            subprocess.run(["sudo", "iptables", "-A", chain, "-m", "owner", "--uid-owner", str(uid),
                            "-m", "comment", "--comment", f"ssh_data_{username}"],
                           check=True, timeout=5)
        except Exception as e:
            log.error(f"Erreur iptables -A {chain}: {e}")
            ok = False
    return ok

def _iptables_remove(username):
    if MOCK_MODE:
        return True
    for chain in ["OUTPUT"]:
        while True:
            try:
                r = subprocess.run(
                    ["sudo", "iptables", "-L", chain, "--line-numbers", "-n"],
                    capture_output=True, text=True, timeout=5
                )
                num = None
                for line in r.stdout.splitlines():
                    if f"ssh_data_{username}" in line:
                        parts = line.strip().split()
                        if parts and parts[0].isdigit():
                            num = int(parts[0])
                            break
                if num is None:
                    break
                subprocess.run(
                    ["sudo", "iptables", "-D", chain, str(num)],
                    check=False, timeout=5
                )
            except Exception:
                break

def _iptables_zero(username):
    if MOCK_MODE:
        return
    for chain in ["OUTPUT"]:
        try:
            r = subprocess.run(
                ["sudo", "iptables", "-L", chain, "--line-numbers", "-n"],
                capture_output=True, text=True, timeout=5
            )
            num = None
            for line in r.stdout.splitlines():
                if f"ssh_data_{username}" in line:
                    parts = line.strip().split()
                    if parts and parts[0].isdigit():
                        num = int(parts[0])
                        break
            if num is not None:
                subprocess.run(
                    ["sudo", "iptables", "-Z", chain, str(num)],
                    check=False, timeout=5
                )
        except Exception:
            pass

def _sync_iptables():
    if MOCK_MODE:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT username, data_limit_mb FROM ssh_users WHERE data_limit_mb > 0")
        for row in c.fetchall():
            _iptables_remove(row[0])
            _iptables_add(row[0])
        conn.close()
    except Exception:
        pass

# ─────────────────────────── DB ────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS ssh_users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            password    TEXT NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at  TIMESTAMP
        )
    ''')
    for col in ["max_conn", "data_limit_mb"]:
        try:
            c.execute(f"ALTER TABLE ssh_users ADD COLUMN {col} INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
    try:
        c.execute("ALTER TABLE ssh_users ADD COLUMN data_used_mb REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE ssh_users ADD COLUMN locked INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()
    _sync_ssh_group_members()
    _sync_iptables()


# ──────────────────────── CRUD ────────────────────────────

def add_user(username, password, expires_at_str, max_conn=0, data_limit_mb=0):
    """Crée un compte Linux SSH avec limites de connexion et data."""
    username = username.strip().lower()
    try:
        expires_at = datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return False, "Format de date invalide. Utiliser YYYY-MM-DD HH:MM"

    if get_user(username):
        return False, f"Le compte SSH {username} existe deja dans la base."
    if not MOCK_MODE and _user_exists(username):
        return False, (
            f"L'utilisateur Linux {username} existe deja. "
            "Choisis un autre nom ou supprime d'abord le compte existant."
        )

    created_system_user = False
    try:
        if not _run(["sudo", "useradd", "-M", "-s", "/bin/false", username]):
            raise Exception(f"Impossible de creer l'utilisateur Linux {username}")
        created_system_user = True
        if not MOCK_MODE:
            proc = subprocess.Popen(["sudo", "chpasswd"], stdin=subprocess.PIPE, text=True)
            proc.communicate(f"{username}:{password}", timeout=5)
            if proc.returncode != 0:
                raise Exception("Impossible de definir le mot de passe SSH")
        if not _run(["sudo", "chage", "-E", "-1", username]):
            raise Exception("Impossible de definir l'expiration systeme")
        if not _run(["sudo", "usermod", "-U", username]):
            raise Exception("Impossible de deverrouiller l'utilisateur Linux")
        if not _add_to_ssh_group(username):
            raise Exception(f"Impossible d'ajouter l'utilisateur au groupe {SSH_GROUP}")

        _limits_conf_add(username, max_conn)
        if data_limit_mb > 0:
            _iptables_add(username)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO ssh_users (username, password, expires_at, max_conn, data_limit_mb, data_used_mb) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (username, password, expires_at.strftime("%Y-%m-%d %H:%M:%S"), max_conn, data_limit_mb),
        )
        conn.commit()
        conn.close()
        return True, "Compte SSH créé avec succès."
    except Exception as e:
        if created_system_user:
            _run(["sudo", "userdel", "-f", username])
        return False, str(e)


def del_user(username):
    """Supprime définitivement un compte Linux SSH."""
    try:
        _run(["sudo", "pkill", "-u", username], check=False)
        _run(["sudo", "userdel", "-r", username], check=False)
        _limits_conf_remove(username)
        _iptables_remove(username)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM ssh_users WHERE username = ?", (username,))
        conn.commit()
        conn.close()
        return True, "Compte SSH supprimé."
    except Exception as e:
        return False, str(e)


def _user_exists(username):
    try:
        subprocess.run(["id", username], check=True, capture_output=True, timeout=5)
        return True
    except:
        return False

def lock_user(username):
    """Verrouille un compte SSH expiré sans le supprimer."""
    if _user_exists(username):
        _run(["sudo", "usermod", "-L", username])
        _run(["sudo", "pkill", "-u", username])
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE ssh_users SET locked=1 WHERE username=?", (username,))
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"Erreur DB lock SSH {username}: {e}")
    return True


def unlock_user(username):
    """Déverrouille un compte SSH (suite à prolongation)."""
    ok = True
    if _user_exists(username):
        ok = _run(["sudo", "usermod", "-U", username])
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE ssh_users SET locked=0 WHERE username=?", (username,))
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"Erreur DB unlock SSH {username}: {e}")
    return ok


def list_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, password, expires_at FROM ssh_users")
    rows = c.fetchall()
    conn.close()
    return rows


def get_user(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, password, expires_at FROM ssh_users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    return row


def update_user_field(username, field, value):
    """Met à jour un champ d'un compte SSH (password, expires_at, max_conn, data_limit_mb)."""
    try:
        if field == "password":
            if not MOCK_MODE and _user_exists(username):
                proc = subprocess.Popen(["sudo", "chpasswd"], stdin=subprocess.PIPE, text=True)
                proc.communicate(f"{username}:{value}", timeout=5)
            col = "password"

        elif field == "expires_at":
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
            if dt.replace(tzinfo=TZ) > _now():
                unlock_user(username)
            col = "expires_at"
            value = dt.strftime("%Y-%m-%d %H:%M:%S")

        elif field == "max_conn":
            max_conn = int(value)
            _limits_conf_remove(username)
            if max_conn > 0:
                _limits_conf_add(username, max_conn)
            col = "max_conn"
            value = max_conn

        elif field == "data_limit_mb":
            dlm = int(value)
            if dlm > 0:
                _iptables_remove(username)
                _iptables_add(username)
            else:
                _iptables_remove(username)
            col = "data_limit_mb"
            value = dlm

        else:
            return False, "Champ inconnu"

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(f"UPDATE ssh_users SET {col}=? WHERE username=?", (value, username))
        conn.commit()
        conn.close()
        return True, "Mise à jour réussie."
    except Exception as e:
        return False, str(e)


def get_expired_users():
    """Retourne la liste des usernames SSH dont l'expiration est dépassée."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = _now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("SELECT username FROM ssh_users WHERE expires_at <= ? AND locked=0", (now,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_user_data_mb(username):
    """Lit les octets iptables pour un user et retourne les MB depuis la dernière remise à zéro."""
    if MOCK_MODE:
        return 0.0
    uid = _get_uid(username)
    if uid is None:
        return 0.0
    total = 0
    for chain in ["OUTPUT"]:
        try:
            r = subprocess.run(
                ["sudo", "iptables", "-L", chain, "-v", "-n", "-x"],
                capture_output=True, text=True, timeout=5
            )
            for line in r.stdout.splitlines():
                if f"ssh_data_{username}" in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            total += int(parts[1])
                        except (ValueError, IndexError):
                            pass
        except Exception as e:
            log.error(f"Erreur iptables -L {chain}: {e}")
    return total / (1024 * 1024)

def update_data_used(username):
    """Lit le compteur iptables, l'ajoute à data_used_mb en DB, puis remet à zéro."""
    if MOCK_MODE:
        return 0.0
    mb = get_user_data_mb(username)
    if mb < 0.01:
        return 0.0
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE ssh_users SET data_used_mb = data_used_mb + ? WHERE username = ?",
                  (mb, username))
        conn.commit()
        conn.close()
        _iptables_zero(username)
    except Exception as e:
        log.error(f"Erreur update_data_used: {e}")
    return mb

def check_proxy_status():
    """Retourne True si ssh-proxy.service est actif."""
    if MOCK_MODE:
        return True
    try:
        r = subprocess.run(
            ["sudo", "-n", "systemctl", "is-active", "ssh-proxy.service"],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


def proxy_action(action):
    """Démarre ou stoppe ssh-proxy.service. action = 'start' | 'stop' | 'restart'"""
    if MOCK_MODE:
        return True, f"ssh-proxy.service {action} (SIMULÉ)"
    try:
        subprocess.run(
            ["sudo", "-n", "systemctl", action, "ssh-proxy.service"],
            check=True, timeout=5
        )
        return True, f"Service SSH proxy {action}."
    except Exception as e:
        return False, str(e)
