"""
ssh_manager.py - Gestionnaire des comptes SSH
Base de données : ssh_accounts.db  (SÉPARÉE de vpn_accounts.db)
NE PAS MÉLANGER avec vpn_manager.py
"""
import sqlite3
import subprocess
import logging
import os
import zoneinfo
from datetime import datetime

log = logging.getLogger(__name__)

DB_PATH = "ssh_accounts.db"          # BDD dédiée SSH - jamais vpn_accounts.db
TZ = zoneinfo.ZoneInfo(os.getenv("TZ", "Africa/Douala"))

# Mode mock : si useradd n'est pas disponible (dev local), simule les commandes
import shutil
MOCK_MODE = False # Bot utilise sudo, pas besoin d'être root directement


def _now():
    return datetime.now(TZ)


def _run(cmd, **kwargs):
    """Lance une commande sudo. En mode mock, logue seulement."""
    if MOCK_MODE:
        log.info(f"[MOCK SSH] {' '.join(cmd)}")
        return True
    try:
        subprocess.run(cmd, check=True, timeout=5, **kwargs)
        return True
    except Exception as e:
        log.error(f"Erreur commande SSH {cmd}: {e}")
        return False


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
    conn.commit()
    conn.close()


# ──────────────────────── CRUD ────────────────────────────

def add_user(username, password, expires_at_str):
    """Crée un compte Linux SSH avec date d'expiration précise."""
    username = username.lower()  # Sécurité : Linux préfère les minuscules
    try:
        expires_at = datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return False, "Format de date invalide. Utiliser YYYY-MM-DD HH:MM"

    exp_date = expires_at.strftime("%Y-%m-%d")
    try:
        _run(["sudo", "useradd", "-M", "-s", "/bin/false", username])

        if not MOCK_MODE:
            proc = subprocess.Popen(["sudo", "chpasswd"], stdin=subprocess.PIPE, text=True)
            proc.communicate(f"{username}:{password}", timeout=5)
            if proc.returncode and proc.returncode != 0:
                raise Exception("chpasswd a échoué")

        _run(["sudo", "chage", "-E", exp_date, username])

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO ssh_users (username, password, expires_at) VALUES (?, ?, ?)",
            (username, password, expires_at.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        conn.close()
        return True, "Compte SSH créé avec succès."
    except Exception as e:
        _run(["sudo", "userdel", "-r", username], stderr=subprocess.DEVNULL)
        return False, str(e)


def del_user(username):
    """Supprime définitivement un compte Linux SSH."""
    try:
        _run(["sudo", "userdel", "-r", username])
        _run(["sudo", "pkill", "-u", username])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM ssh_users WHERE username = ?", (username,))
        conn.commit()
        conn.close()
        return True, "Compte SSH supprimé."
    except Exception as e:
        return False, str(e)


def lock_user(username):
    """Verrouille un compte SSH expiré sans le supprimer."""
    ok1 = _run(["sudo", "usermod", "-L", username])
    _run(["sudo", "pkill", "-u", username])
    return ok1


def unlock_user(username):
    """Déverrouille un compte SSH (suite à prolongation)."""
    return _run(["sudo", "usermod", "-U", username])


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
    """Met à jour un champ d'un compte SSH (password ou expires_at)."""
    try:
        if field == "password":
            if not MOCK_MODE:
                proc = subprocess.Popen(["sudo", "chpasswd"], stdin=subprocess.PIPE, text=True)
                proc.communicate(f"{username}:{value}", timeout=5)
            col = "password"

        elif field == "expires_at":
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
            _run(["sudo", "chage", "-E", dt.strftime("%Y-%m-%d"), username])
            # Si la nouvelle date est dans le futur → déverrouille le compte
            if dt.replace(tzinfo=TZ) > _now():
                unlock_user(username)
            col = "expires_at"
            value = dt.strftime("%Y-%m-%d %H:%M:%S")

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
    c.execute("SELECT username FROM ssh_users WHERE expires_at <= ?", (now,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


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
