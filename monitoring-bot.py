import os, json, logging, time, platform, subprocess, re, sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import psutil
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import vpn_manager
import ssh_manager

BASE_DIR = Path(__file__).parent.resolve()
CHAT_ID_FILE = BASE_DIR / ".bot_chat_ids.json"
ENV_FILE = BASE_DIR / ".env_bot"
ADMIN_LINK = "t.me/King_premium_N5"

logging.basicConfig(level=logging.INFO, style="{", format="{asctime} [{levelname}] {message}")
log = logging.getLogger(__name__)

chat_ids = set()
if CHAT_ID_FILE.exists():
    chat_ids = set(json.loads(CHAT_ID_FILE.read_text()))

def save():
    CHAT_ID_FILE.write_text(json.dumps(list(chat_ids)))

def reg(cid):
    chat_ids.add(cid)
    save()

# ── Auth codes guest ──
AUTH_CODES_FILE = BASE_DIR / ".auth_codes.json"
AUTHORIZED_FILE = BASE_DIR / ".authorized_ids.json"

auth_codes = {}
authorized_ids = set()
if AUTH_CODES_FILE.exists():
    auth_codes = json.loads(AUTH_CODES_FILE.read_text())
if AUTHORIZED_FILE.exists():
    authorized_ids = set(json.loads(AUTHORIZED_FILE.read_text()))

def _save_codes():
    AUTH_CODES_FILE.write_text(json.dumps(auth_codes))
def _save_auth():
    AUTHORIZED_FILE.write_text(json.dumps(list(authorized_ids)))

def _get_admin():
    v = os.getenv("ADMIN_CHAT_ID")
    if v: return v.strip()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == "ADMIN_CHAT_ID":
                    return v.strip().strip("\"'")
    return None

def is_admin(cid):
    a = _get_admin()
    return a is not None and str(cid) == a

def is_authorized(cid):
    return is_admin(cid) or cid in authorized_ids

async def _req_auth(upd):
    if not is_authorized(upd.effective_chat.id):
        await upd.message.reply_text(f"\u26d4 Acces refuse. Contacte l'admin : {ADMIN_LINK}\nou utilise /auth CODE.")
        return False
    return True

async def _req_admin(upd):
    if not is_admin(upd.effective_chat.id):
        await upd.message.reply_text("\u26d4 Reserve a l'admin.")
        return False
    return True

def scale(n):
    for u in ["B","KB","MB","GB","TB"]:
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}PB"

def upt(s):
    d = int(s//86400)
    h = int((s%86400)//3600)
    m = int((s%3600)//60)
    return f"{d}j {h}h {m}m"

def _bar(pct, width=10):
    filled = round(pct / 100 * width)
    empty = width - filled
    return "\u2588" * filled + "\u2591" * empty

def _exp_presets_kb(prefix="exp"):
    kb = [
        [InlineKeyboardButton("+1j", callback_data=f"{prefix}_1"),
         InlineKeyboardButton("+3j", callback_data=f"{prefix}_3"),
         InlineKeyboardButton("+7j", callback_data=f"{prefix}_7")],
        [InlineKeyboardButton("+15j", callback_data=f"{prefix}_15"),
         InlineKeyboardButton("+30j", callback_data=f"{prefix}_30"),
         InlineKeyboardButton("+60j", callback_data=f"{prefix}_60")],
        [InlineKeyboardButton("+90j", callback_data=f"{prefix}_90"),
         InlineKeyboardButton("\u270f\ufe0f Saisir date", callback_data=f"{prefix}_manual")],
    ]
    return InlineKeyboardMarkup(kb)

def _exp_time_kb(prefix):
    kb = [
        [InlineKeyboardButton("00:00", callback_data=f"{prefix}t_0000"),
         InlineKeyboardButton("06:00", callback_data=f"{prefix}t_0600"),
         InlineKeyboardButton("12:00", callback_data=f"{prefix}t_1200")],
        [InlineKeyboardButton("18:00", callback_data=f"{prefix}t_1800"),
         InlineKeyboardButton("23:59", callback_data=f"{prefix}t_2359")],
        [InlineKeyboardButton("\u2b05\ufe0f Retour", callback_data=f"{prefix}t_back")],
    ]
    return InlineKeyboardMarkup(kb)

def refresh_btn(cmd):
    return InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f504 Rafraichir", callback_data=f"r_{cmd}")]])

def get_token():
    t = os.getenv("TELEGRAM_BOT_TOKEN")
    if t: return t
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == "TELEGRAM_BOT_TOKEN":
                    return v.strip().strip("\"'")
    return None

async def start(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = upd.effective_chat.id
    reg(cid)
    if is_admin(cid):
        await upd.message.reply_text(
            "\U0001f916 Monitoring Bot\n"
            f"{'='*28}\n"
            "\U0001f4a1 Admin : acces total\n"
            "\U0001f447 /grant pour creer un code invite\n"
            "\U0001f447 /vpn ou /ssh pour gerer les acces\n"
            "\U0001f447 /help pour les commandes"
        )
    elif is_authorized(cid):
        await upd.message.reply_text(
            "\U0001f916 Monitoring Bot\n"
            f"{'='*28}\n"
            "\U0001f4a1 Acces invite - Monitoring seulement\n"
            "\U0001f447 /status, /cpu, /ram, /disk, /gpu, /network, /system"
        )
    else:
        await upd.message.reply_text(
            "\u26d4 <b>Acces refusé</b>\n"
            "Ce bot est privé. Contacte l'administrateur pour obtenir un code d'accès.\n\n"
            "Utilise <code>/auth VOTRE_CODE</code> pour te connecter.",
            parse_mode="HTML"
        )

async def grant(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = upd.effective_chat.id
    if not is_admin(cid):
        await upd.message.reply_text("\u26d4 Reserve a l'admin.")
        return
    import secrets, string
    code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    auth_codes[code] = True
    _save_codes()
    await upd.message.reply_text(
        f"\U0001f511 <b>Code invite generé</b>\n"
        f"<code>{code}</code>\n\n"
        f"Valable pour une seule connexion. Envoie-le à ton invite.",
        parse_mode="HTML"
    )

async def auth(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = upd.effective_chat.id
    if is_authorized(cid):
        await upd.message.reply_text("Tu es déjà connecté.")
        return
    parts = upd.message.text.strip().split(None, 1)
    if len(parts) < 2:
        await upd.message.reply_text("Utilise : <code>/auth CODE</code>", parse_mode="HTML")
        return
    code = parts[1].strip()
    if code in auth_codes and auth_codes[code]:
        authorized_ids.add(cid)
        _save_auth()
        del auth_codes[code]
        _save_codes()
        await upd.message.reply_text(
            "\u2705 <b>Connexion réussie !</b>\n"
            "Tu as maintenant accès au monitoring du serveur.\n"
            "Tape /start pour voir les commandes disponibles.",
            parse_mode="HTML"
        )
    else:
        await upd.message.reply_text(f"Code invalide ou déjà utilisé.\nContacte l'admin : {ADMIN_LINK}")

def build_status():
    cpup = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    load = os.getloadavg()
    boot = datetime.fromtimestamp(psutil.boot_time())
    return (
        f"\U0001f4ca TABLEAU DE BORD\n"
        f"{'='*28}\n"
        f"\U0001f5a5 {platform.node()}\n"
        f"\U0001f310 {platform.system()} {platform.release()}\n\n"
        f"\U0001f5a5 CPU    {cpup:>3}%  {_bar(cpup)}\n"
        f"\U0001f9e0 RAM    {mem.percent:>3}%  {_bar(mem.percent)}\n"
        f"\U0001f4be Disque {disk.percent:>3}%  {_bar(disk.percent)}\n\n"
        f"\U0001f4e6 Reseau: \u2b07 {scale(net.bytes_recv)} / \u2b06 {scale(net.bytes_sent)}\n"
        f"\u23f1 Uptime: {upt(time.time()-psutil.boot_time())}\n"
        f"\U0001f504 Boot: {boot.strftime('%Y-%m-%d %H:%M')}"
    )

async def status(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _req_auth(upd): return
    reg(upd.effective_chat.id)
    await upd.message.reply_text(build_status(), reply_markup=refresh_btn("status"))

def build_system():
    boot = datetime.fromtimestamp(psutil.boot_time())
    users = psutil.users()
    return (
        f"\U0001f5a5 INFORMATIONS SYSTEME\n"
        f"{'='*28}\n"
        f"Hostname : {platform.node()}\n"
        f"OS       : {platform.system()} {platform.release()}\n"
        f"Arch     : {platform.machine()}\n"
        f"Kernel   : {platform.version().split()[0]}\n"
        f"\u23f1 Uptime  : {upt(time.time()-psutil.boot_time())}\n"
        f"\U0001f504 Boot    : {boot.strftime('%Y-%m-%d %H:%M')}\n"
        f"\U0001f465 Users   : {len(users)} connecte(s)"
    )

async def system(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _req_auth(upd): return
    reg(upd.effective_chat.id)
    await upd.message.reply_text(build_system(), reply_markup=refresh_btn("system"))

def build_cpu():
    cpup = psutil.cpu_percent(interval=1)
    cores = psutil.cpu_count()
    freq = psutil.cpu_freq()
    load = os.getloadavg()
    freq_line = f"Freq  : {freq.current:.0f} MHz" if freq else ""
    return (
        f"\U0001f5a5 CPU\n"
        f"{'='*28}\n"
        f"Usage : {cpup:>3}%  {_bar(cpup)}\n"
        f"Load  : {load[0]:.2f} / {load[1]:.2f} / {load[2]:.2f}\n"
        f"Coeurs: {cores}\n"
        f"{freq_line}"
    )

async def cpu(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _req_auth(upd): return
    reg(upd.effective_chat.id)
    await upd.message.reply_text(build_cpu(), reply_markup=refresh_btn("cpu"))

def build_ram():
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return (
        f"\U0001f9e0 RAM\n"
        f"{'='*28}\n"
        f"{_bar(mem.percent)}\n"
        f"Total    : {scale(mem.total)}\n"
        f"Utilise  : {scale(mem.used)} ({mem.percent}%)\n"
        f"Libre    : {scale(mem.available)}\n"
        f"Buff/Cache: {scale(mem.total - mem.used - mem.available)}\n"
        f"\n"
        f"\U0001f504 Swap\n"
        f"{'─'*20}\n"
        f"Total    : {scale(swap.total)}\n"
        f"Utilise  : {scale(swap.used)} ({swap.percent}%)\n"
        f"Libre    : {scale(swap.free)}"
    )

async def ram(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _req_auth(upd): return
    reg(upd.effective_chat.id)
    await upd.message.reply_text(build_ram(), reply_markup=refresh_btn("ram"))

def build_disk():
    d = psutil.disk_usage("/")
    io = psutil.disk_io_counters()
    return (
        f"\U0001f4be DISQUE\n"
        f"{'='*28}\n"
        f"{_bar(d.percent)}\n"
        f"Total   : {scale(d.total)}\n"
        f"Utilise : {scale(d.used)} ({d.percent}%)\n"
        f"Libre   : {scale(d.free)}\n"
        f"\n"
        f"\U0001f504 Entrees/Sorties\n"
        f"{'─'*20}\n"
        f"\U0001f7e2 Lu    : {scale(io.read_bytes)}\n"
        f"\U0001f534 Ecrit : {scale(io.write_bytes)}"
    )

async def disk(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _req_auth(upd): return
    reg(upd.effective_chat.id)
    await upd.message.reply_text(build_disk(), reply_markup=refresh_btn("disk"))

def build_gpu():
    try:
        out = subprocess.run(
            ["nvidia-smi","--query-gpu=name,utilization.gpu,memory.total,memory.used,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0 and out.stdout.strip():
            p = [x.strip() for x in out.stdout.split(",")]
            return (
                f"\U0001f3ae GPU NVIDIA\n"
                f"{'='*28}\n"
                f"Modele : {p[0]}\n"
                f"Usage  : {p[1]:>3}%  {_bar(int(p[1]))}\n"
                f"VRAM   : {p[3]} / {p[2]} MB\n"
                f"Temp   : {p[4]}C"
            )
    except:
        pass
    return "\U0001f3ae GPU\nNon disponible"

async def gpu(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _req_auth(upd): return
    reg(upd.effective_chat.id)
    await upd.message.reply_text(build_gpu(), reply_markup=refresh_btn("gpu"))

_last_net = {"bytes": None, "time": 0}

def build_network():
    global _last_net
    net_all = psutil.net_io_counters(pernic=True)
    lines = ["\U0001f4e1 RESEAU", f"{'='*28}", "Depuis le demarrage :", ""]
    total_rx = 0
    total_tx = 0
    for name, stats in sorted(net_all.items()):
        if name == "lo":
            continue
        total_rx += stats.bytes_recv
        total_tx += stats.bytes_sent
        ifup = "\U0001f7e2" if stats.bytes_recv > 0 or stats.bytes_sent > 0 else "\U0001f534"
        lines.append(
            f"{ifup} {name}"
            f"\n   \u2b07 Recu  : {scale(stats.bytes_recv)}"
            f"\n   \u2b06 Envoye: {scale(stats.bytes_sent)}"
            f"\n   \u26a0 Erreurs: {stats.errin}/{stats.errout}  Pertes: {stats.dropin}/{stats.dropout}"
            f"\n"
        )

    now = time.time()
    net_total = psutil.net_io_counters()
    speed_rx = 0
    speed_tx = 0
    if _last_net["bytes"] is not None:
        dt = now - _last_net["time"]
        if dt > 0:
            speed_rx = (net_total.bytes_recv - _last_net["bytes"].bytes_recv) / dt
            speed_tx = (net_total.bytes_sent - _last_net["bytes"].bytes_sent) / dt
    _last_net["bytes"] = net_total
    _last_net["time"] = now

    if total_rx > 0 or total_tx > 0:
        lines.append(f"\U0001f4ca Total: \u2b07 {scale(total_rx)} / \u2b06 {scale(total_tx)}")
    if speed_rx > 0 or speed_tx > 0:
        lines.append(f"\U0001f4a8 Vitesse: \u2b07 {scale(speed_rx)}/s / \u2b06 {scale(speed_tx)}/s")

    return "\n".join(lines)

async def network(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _req_auth(upd): return
    reg(upd.effective_chat.id)
    await upd.message.reply_text(build_network(), reply_markup=refresh_btn("network"))

async def help(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _req_auth(upd): return
    reg(upd.effective_chat.id)
    await upd.message.reply_text(
        "\U0001f916 <b>Commandes disponibles</b>\n"
        f"{'='*28}\n\n"
        "\U0001f9ed <b>Surveillance Serveur</b>\n"
        "\U0001f4ca /status  - Tableau de bord complet\n"
        "\U0001f5a5 /system  - OS, kernel, uptime, users\n"
        "\U0001f5a5 /cpu     - Utilisation CPU, charge, frequence\n"
        "\U0001f9e0 /ram     - RAM et Swap (total, utilise, libre)\n"
        "\U0001f4be /disk    - Disque et E/S\n"
        "\U0001f3ae /gpu     - GPU NVIDIA (usage, VRAM, temperature)\n"
        "\U0001f4e1 /network - Stats reseau par interface + vitesse\n\n"
        "\U0001f6e1 <b>Gestion des Acces</b>\n"
        "\U0001f5e1 /vpn     - Gestion VPN (ZiVPN UDP port 443)\n"
        "\U0001f511 /ssh     - Gestion SSH Payload (ports 2053/8443)\n"
        "   \u2192 Creer/supprimer/modifier comptes\n"
        "   \u2192 Limiter connexions simultanees\n"
        "   \u2192 Quota data (MB)\n\n"
        "\U0001f514 <b>Alertes automatiques</b>\n"
        "\u2022 CPU > 80%  |  RAM > 85%  |  Disque > 85%\n"
        "\u2022 Comptes expires verrouilles + notifies\n"
        "\u2022 Quota data SSH verifie toutes les 60s\n\n"
        "\U0001f539 /help - Cette aide"
    , parse_mode="HTML")

# --- VPN CRM LOGIC ---
# --- VPN CRM LOGIC ---
W_USER, W_PASS, W_DUR = range(3)
W_EDIT_PASS, W_EDIT_EXP = range(3, 5)

async def vpn_menu(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _req_admin(upd): return
    vpn_manager.init_db()
    st = vpn_manager.check_zivpn_status()
    st_text = "🟢 ALLUMÉ" if st else "🔴 ÉTEINT"
    st_btn = "🔴 Stopper ZiVPN" if st else "🟢 Lancer ZiVPN"
    st_cb = "vpn_stop" if st else "vpn_start"

    kb = [
        [InlineKeyboardButton("➕ Nouveau Compte", callback_data="vpn_new")],
        [InlineKeyboardButton("📋 Liste des Comptes", callback_data="vpn_list")],
        [InlineKeyboardButton("🗑 Supprimer un Compte", callback_data="vpn_del_menu")],
        [InlineKeyboardButton(st_btn, callback_data=st_cb)]
    ]
    txt = f"🛡️ <b>Gestionnaire VPN (ZiVPN)</b>\nÉtat du serveur : {st_text}\n\nQue veux-tu faire ?"
    if upd.message:
        await upd.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    else:
        await upd.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def vpn_cb(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    if not is_admin(upd.effective_chat.id):
        await q.message.reply_text("\u26d4 Reserve a l'admin.")
        return ConversationHandler.END
    d = q.data

    if d == "vpn_start" or d == "vpn_stop":
        act = "start" if d == "vpn_start" else "stop"
        ok, msg = vpn_manager.zivpn_action(act)
        await q.message.reply_text(f"Action : {msg}")
        await vpn_menu(upd, ctx)
        return ConversationHandler.END

    if d == "vpn_list":
        rows = vpn_manager.list_users()
        if not rows:
            await q.message.reply_text("Aucun compte VPN actif.")
        else:
            kb = []
            for r in rows:
                kb.append([InlineKeyboardButton(f"👤 {r[0]} (Exp: {r[2]})", callback_data=f"vpninfo_{r[0]}")])
            await q.message.reply_text("📋 <b>Sélectionnez un compte pour le gérer :</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return ConversationHandler.END

    if d.startswith("vpninfo_"):
        user = d.split("_", 1)[1]
        row = vpn_manager.get_user(user)
        if not row:
            await q.message.reply_text("Compte introuvable.")
            return ConversationHandler.END
        u, p, exp = row
        out = (
            f"👤 <b>Compte : {u}</b>\n"
            f"🔑 Pass : <code>{p}</code>\n"
            f"⏳ Expire : {exp}\n"
        )
        kb = [
            [InlineKeyboardButton("✏️ Changer Pass", callback_data=f"editpass_{u}")],
            [InlineKeyboardButton("⏳ Changer Date Expiration", callback_data=f"editexp_{u}")],
            [InlineKeyboardButton("❌ Supprimer le Compte", callback_data=f"vpndel_{u}")]
        ]
        await q.message.reply_text(out, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return ConversationHandler.END

    if d.startswith("editpass_"):
        ctx.user_data['edit_user'] = d.split("_", 1)[1]
        await q.message.reply_text("🔑 Entrez le **nouveau mot de passe** :", parse_mode="Markdown")
        return W_EDIT_PASS

    if d.startswith("editexp_"):
        ctx.user_data['edit_user'] = d.split("_", 1)[1]
        await q.message.reply_text("\u23f3 Choisis la durée avant expiration :", reply_markup=_exp_presets_kb("exp"))
        return W_EDIT_EXP

    if d == "vpn_del_menu":
        rows = vpn_manager.list_users()
        if not rows:
            await q.message.reply_text("Aucun compte à supprimer.")
            return ConversationHandler.END
        kb = [[InlineKeyboardButton(f"❌ {r[0]}", callback_data=f"vpndel_{r[0]}")] for r in rows]
        await q.message.reply_text("Quel compte veux-tu supprimer ?", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END

    if d.startswith("vpndel_"):
        user = d.split("_", 1)[1]
        ok, msg = vpn_manager.del_user(user)
        await q.message.reply_text(f"Suppression de {user} : {msg}")
        return ConversationHandler.END

    if d == "vpn_new":
        await q.message.reply_text("👤 Entrez le **nom d'utilisateur** pour le nouveau compte VPN :", parse_mode="Markdown")
        return W_USER

async def v_user(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['v_user'] = upd.message.text.strip()
    await upd.message.reply_text("🔑 Entrez le **mot de passe** :", parse_mode="Markdown")
    return W_PASS

async def v_pass(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['v_pass'] = upd.message.text.strip()
    await upd.message.reply_text("\u23f3 Choisis la durée avant expiration :", reply_markup=_exp_presets_kb("dur"))
    return W_DUR

async def v_dur_preset(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    days = int(q.data.split("_")[1])
    ctx.user_data['v_dur_days'] = days
    await q.message.edit_text(f"\u23f3 Choisis l'heure pour +{days}j :", reply_markup=_exp_time_kb("dur"))
    return W_DUR

async def v_dur_set_time(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    days = ctx.user_data.get('v_dur_days', 1)
    ts = q.data.split("_")[-1]
    dt = datetime.now(vpn_manager.TZ) + timedelta(days=days)
    dt = dt.replace(hour=int(ts[:2]), minute=int(ts[2:]), second=0, microsecond=0)
    ctx.user_data['v_dur'] = dt.strftime("%Y-%m-%d %H:%M")
    return await _create_account(upd, ctx)

async def v_dur_back(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    await q.message.edit_text("\u23f3 Choisis la durée avant expiration :", reply_markup=_exp_presets_kb("dur"))
    return W_DUR

async def v_dur_manual(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    await q.message.reply_text("\u23f3 Entrez la **date et heure** au format `YYYY-MM-DD HH:MM` (ex: 2026-08-20 14:30) :", parse_mode="Markdown")
    return W_DUR

async def v_dur_text(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = upd.message.text.strip()
    try:
        datetime.strptime(val, "%Y-%m-%d %H:%M")
        ctx.user_data['v_dur'] = val
        return await _create_account(upd, ctx)
    except:
        await upd.message.reply_text("Format invalide. Veuillez entrer la date au format `YYYY-MM-DD HH:MM`.")
        return W_DUR

async def _create_account(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = ctx.user_data['v_user']
    p = ctx.user_data['v_pass']
    d = ctx.user_data['v_dur']

    msg_obj = upd.message or upd.callback_query.message
    await msg_obj.reply_text("⏳ Création du compte en cours sur le serveur...")
    ok, msg = vpn_manager.add_user(u, p, d)

    if ok:
        import urllib.request
        ip = "127.0.0.1"
        try: ip = urllib.request.urlopen("https://api.ipify.org").read().decode('utf8')
        except: pass

        res = (
            f"🟢 <b>Compte VPN Créé avec Succès !</b>\n\n"
            f"🌐 <b>Host / IP</b> : <code>{ip}</code>\n"
            f"🔌 <b>Port UDP</b> : <code>443</code>\n"
            f"👤 <b>User</b> : <code>{u}</code>\n"
            f"🔑 <b>Pass</b> : <code>{p}</code>\n"
            f"⏳ <b>Expire le</b> : {d}\n"
        )
        await msg_obj.reply_text(res, parse_mode="HTML")
    else:
        await msg_obj.reply_text(f"❌ Erreur lors de la création : {msg}")
    return ConversationHandler.END

async def edit_pass(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ctx.user_data['edit_user']
    val = upd.message.text.strip()
    ok, msg = vpn_manager.update_user_field(user, "password", val)
    await upd.message.reply_text(f"Mise à jour du mot de passe de {user} : {msg}")
    return ConversationHandler.END

async def edit_exp_preset(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    days = int(q.data.split("_")[1])
    ctx.user_data['edit_days'] = days
    await q.message.edit_text(f"\u23f3 Choisis l'heure pour +{days}j :", reply_markup=_exp_time_kb("exp"))
    return W_EDIT_EXP

async def edit_exp_set_time(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    user = ctx.user_data.get('edit_user')
    if not user:
        await q.message.edit_text("Erreur : utilisateur inconnu.")
        return ConversationHandler.END
    days = ctx.user_data.get('edit_days', 1)
    ts = q.data.split("_")[-1]
    dt = datetime.now(vpn_manager.TZ) + timedelta(days=days)
    dt = dt.replace(hour=int(ts[:2]), minute=int(ts[2:]), second=0, microsecond=0)
    ok, msg = vpn_manager.update_user_field(user, "expires_at", dt.strftime("%Y-%m-%d %H:%M"))
    await q.message.edit_text(f"Mise à jour de l'expiration de {user} : {msg}")
    return ConversationHandler.END

async def edit_exp_back(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    await q.message.edit_text("\u23f3 Choisis la durée avant expiration :", reply_markup=_exp_presets_kb("exp"))
    return W_EDIT_EXP

async def edit_exp_manual(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    await q.message.reply_text("\u23f3 Entrez la **nouvelle date** au format `YYYY-MM-DD HH:MM`\nExemple : `2026-08-20 14:30`", parse_mode="Markdown")
    return W_EDIT_EXP

async def edit_exp_text(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ctx.user_data['edit_user']
    val = upd.message.text.strip()
    ok, msg = vpn_manager.update_user_field(user, "expires_at", val)
    await upd.message.reply_text(f"Mise à jour de l'expiration de {user} : {msg}")
    return ConversationHandler.END

async def v_cancel(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await upd.message.reply_text("Opération annulée.")
    return ConversationHandler.END

# --- END VPN CRM ---

# ══════════════════════════════════════════════════════
# ===              SSH CRM (/ssh)                    ===
# ══════════════════════════════════════════════════════
# États SSH : range(10, 15) pour ne pas chevaucher les états VPN (0-4)
SSH_W_USER, SSH_W_PASS, SSH_W_DUR = range(10, 13)
SSH_W_EDIT_PASS, SSH_W_EDIT_EXP  = range(13, 15)
SSH_W_CONN = 15
SSH_W_DATA = 16

async def ssh_menu(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _req_admin(upd): return
    ssh_manager.init_db()
    st = ssh_manager.check_proxy_status()
    st_text = "🟢 ALLUMÉ" if st else "🔴 ÉTEINT"
    st_btn  = "🔴 Stopper le Proxy SSH" if st else "🟢 Lancer le Proxy SSH"
    st_cb   = "ssh_stop" if st else "ssh_start"
    kb = [
        [InlineKeyboardButton("➕ Nouveau Compte SSH", callback_data="ssh_new")],
        [InlineKeyboardButton("📋 Liste des Comptes", callback_data="ssh_list")],
        [InlineKeyboardButton("🗑 Supprimer un Compte", callback_data="ssh_del_menu")],
        [InlineKeyboardButton(st_btn, callback_data=st_cb)],
    ]
    txt = (
        f"🔐 <b>Gestionnaire SSH (TCP Payload)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 HTTP Injection : Port <code>2053</code>\n"
        f"🔒 SSL Passthrough : Port <code>8443</code>\n"
        f"Proxy : {st_text}\n\n"
        "Que veux-tu faire ?"
    )
    if upd.message:
        await upd.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    else:
        await upd.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def ssh_cb(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    if not is_admin(upd.effective_chat.id):
        await q.message.reply_text("\u26d4 Reserve a l'admin.")
        return ConversationHandler.END
    d = q.data

    # ── ON / OFF du proxy ──
    if d in ("ssh_start", "ssh_stop"):
        action = "start" if d == "ssh_start" else "stop"
        ok, msg = ssh_manager.proxy_action(action)
        await q.message.reply_text(f"Proxy SSH : {msg}")
        await ssh_menu(upd, ctx)
        return ConversationHandler.END
    if d == "ssh_list":
        rows = ssh_manager.list_users()
        if not rows:
            await q.message.reply_text("Aucun compte SSH actif.")
        else:
            kb = [[InlineKeyboardButton(f"👤 {r[0]} (Exp: {r[2]})", callback_data=f"sshinfo_{r[0]}")] for r in rows]
            await q.message.reply_text("📋 <b>Sélectionnez un compte :</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return ConversationHandler.END

    if d.startswith("sshinfo_"):
        user = d.split("_", 1)[1]
        row = ssh_manager.get_user(user)
        if not row:
            await q.message.reply_text("Compte introuvable.")
            return ConversationHandler.END

        conn = sqlite3.connect("ssh_accounts.db")
        c = conn.cursor()
        c.execute("SELECT max_conn, data_limit_mb, data_used_mb FROM ssh_users WHERE username=?", (user,))
        extra = c.fetchone()
        conn.close()

        u, p, exp = row
        mc, dlm, dum = extra if extra else (0, 0, 0)
        lims = ""
        if mc > 0:
            lims += f"🔗 Max connexions : {mc}\n"
        if dlm > 0:
            rem = max(0, dlm - dum)
            lims += f"💾 Data : {dum:.1f}/{dlm} MB ({rem:.0f} MB restant)\n"
        out = (
            f"👤 <b>Compte SSH : {u}</b>\n"
            f"🔑 Pass : <code>{p}</code>\n"
            f"⏳ Expire : {exp}\n"
            f"{lims}"
        )
        kb = [
            [InlineKeyboardButton("✏️ Changer Pass", callback_data=f"ssheditpass_{u}")],
            [InlineKeyboardButton("⏳ Changer Expiration", callback_data=f"ssheditexp_{u}")],
            [InlineKeyboardButton("❌ Supprimer", callback_data=f"sshdel_{u}")],
        ]
        await q.message.reply_text(out, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return ConversationHandler.END

    if d == "ssh_del_menu":
        rows = ssh_manager.list_users()
        if not rows:
            await q.message.reply_text("Aucun compte SSH à supprimer.")
            return ConversationHandler.END
        kb = [[InlineKeyboardButton(f"❌ {r[0]}", callback_data=f"sshdel_{r[0]}")] for r in rows]
        await q.message.reply_text("Quel compte SSH supprimer ?", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END

    if d.startswith("sshdel_"):
        user = d.split("_", 1)[1]
        ok, msg = ssh_manager.del_user(user)
        await q.message.reply_text(f"Suppression SSH {user} : {msg}")
        return ConversationHandler.END

    if d == "ssh_new":
        await q.message.reply_text("👤 Entrez le **nom d'utilisateur** SSH :", parse_mode="Markdown")
        return SSH_W_USER

    if d.startswith("ssheditpass_"):
        ctx.user_data['ssh_edit_user'] = d.split("_", 1)[1]
        await q.message.reply_text("🔑 Entrez le **nouveau mot de passe** :", parse_mode="Markdown")
        return SSH_W_EDIT_PASS

    if d.startswith("ssheditexp_"):
        ctx.user_data['ssh_edit_user'] = d.split("_", 1)[1]
        await q.message.reply_text("\u23f3 Choisis la durée avant expiration :", reply_markup=_exp_presets_kb("sshexp"))
        return SSH_W_EDIT_EXP

async def ssh_v_user(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['ssh_user'] = upd.message.text.strip()
    await upd.message.reply_text("🔑 Entrez le **mot de passe** :", parse_mode="Markdown")
    return SSH_W_PASS

async def ssh_v_pass(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['ssh_pass'] = upd.message.text.strip()
    await upd.message.reply_text("\u23f3 Choisis la durée avant expiration :", reply_markup=_exp_presets_kb("sshdur"))
    return SSH_W_DUR

async def ssh_v_dur_preset(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    days = int(q.data.split("_")[1])
    ctx.user_data['ssh_dur_days'] = days
    await q.message.edit_text(f"\u23f3 Choisis l'heure pour +{days}j :", reply_markup=_exp_time_kb("sshdur"))
    return SSH_W_DUR

async def ssh_v_dur_set_time(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    days = ctx.user_data.get('ssh_dur_days', 1)
    ts = q.data.split("_")[-1]
    dt = datetime.now(vpn_manager.TZ) + timedelta(days=days)
    dt = dt.replace(hour=int(ts[:2]), minute=int(ts[2:]), second=0, microsecond=0)
    ctx.user_data['ssh_dur'] = dt.strftime("%Y-%m-%d %H:%M")
    await q.message.reply_text(
        "\U0001f517 **Limite de connexions simultanées** (optionnel)\n"
        "Combien de connexions SSH max ? (ex: `2`, ou `0` pour illimité)",
        parse_mode="Markdown"
    )
    return SSH_W_CONN

async def ssh_v_dur_back(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    await q.message.edit_text("\u23f3 Choisis la durée avant expiration :", reply_markup=_exp_presets_kb("sshdur"))
    return SSH_W_DUR

async def ssh_v_dur_manual(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    await q.message.reply_text("\u23f3 Entrez la **date et heure** au format `YYYY-MM-DD HH:MM`\nExemple : `2026-08-01 23:59`", parse_mode="Markdown")
    return SSH_W_DUR

async def ssh_v_dur_text(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = upd.message.text.strip()
    try:
        datetime.strptime(val, "%Y-%m-%d %H:%M")
    except ValueError:
        await upd.message.reply_text("Format invalide. Entrez la date au format `YYYY-MM-DD HH:MM`.")
        return SSH_W_DUR
    ctx.user_data['ssh_dur'] = val
    await upd.message.reply_text(
        "\U0001f517 **Limite de connexions simultanées** (optionnel)\n"
        "Combien de connexions SSH max ? (ex: `2`, ou `0` pour illimité)",
        parse_mode="Markdown"
    )
    return SSH_W_CONN

async def ssh_v_conn(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = upd.message.text.strip()
    try:
        max_conn = int(val)
        if max_conn < 0:
            raise ValueError
    except ValueError:
        await upd.message.reply_text("Invalide. Entre un nombre entier (ex: `2`) ou `0` pour illimité.", parse_mode="Markdown")
        return SSH_W_CONN
    ctx.user_data['ssh_max_conn'] = max_conn
    await upd.message.reply_text(
        "💾 **Limite de données** (optionnel)\n"
        "Combien de MB maximum ? (ex: `500`, ou `0` pour illimité)",
        parse_mode="Markdown"
    )
    return SSH_W_DATA

async def ssh_v_data(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = upd.message.text.strip()
    try:
        data_limit = int(val)
        if data_limit < 0:
            raise ValueError
    except ValueError:
        await upd.message.reply_text("Invalide. Entre un nombre en MB (ex: `500`) ou `0` pour illimité.", parse_mode="Markdown")
        return SSH_W_DATA
    ctx.user_data['ssh_data_limit'] = data_limit
    return await _create_ssh_account(upd, ctx)

async def _create_ssh_account(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = ctx.user_data['ssh_user']
    p = ctx.user_data['ssh_pass']
    d = ctx.user_data['ssh_dur']
    mc = ctx.user_data.get('ssh_max_conn', 0)
    dl = ctx.user_data.get('ssh_data_limit', 0)

    msg_obj = upd.message or upd.callback_query.message
    await msg_obj.reply_text("⏳ Création du compte SSH en cours...")
    ok, msg = ssh_manager.add_user(u, p, d, max_conn=mc, data_limit_mb=dl)

    if ok:
        import urllib.request
        ip = "127.0.0.1"
        try: ip = urllib.request.urlopen("https://api.ipify.org").read().decode('utf8')
        except: pass
        limits = ""
        if mc > 0:
            limits += f"🔗 Max connexions : {mc}\n"
        if dl > 0:
            limits += f"💾 Quota data : {dl} MB\n"
        res = (
            f"✅ <b>Compte SSH Créé !</b>\n\n"
            f"━━━━━━ CONNEXION ━━━━━━\n"
            f"🌐 <b>Host</b>   : <code>{ip}</code>\n"
            f"👤 <b>User</b>   : <code>{u}</code>\n"
            f"🔑 <b>Pass</b>   : <code>{p}</code>\n"
            f"⏳ <b>Expire</b> : {d}\n"
            f"{limits}"
            f"━━━━━━━ PORTS ─────────\n"
            f"📡 HTTP Injection : <code>2053</code>\n"
            f"🔒 SSL Payload    : <code>8443</code>\n\n"
            f"━━━━━━ PAYLOAD EXEMPLE ─────\n"
            f"<code>GET / HTTP/1.1[crlf]Host: free.orange.cm[crlf]Connection: Upgrade[crlf][crlf]</code>"
        )
        await msg_obj.reply_text(res, parse_mode="HTML")
    else:
        await msg_obj.reply_text(f"❌ Erreur : {msg}")
    return ConversationHandler.END

async def ssh_edit_pass(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ctx.user_data['ssh_edit_user']
    ok, msg = ssh_manager.update_user_field(user, "password", upd.message.text.strip())
    await upd.message.reply_text(f"Mot de passe SSH de {user} : {msg}")
    return ConversationHandler.END

async def ssh_edit_exp_preset(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    days = int(q.data.split("_")[1])
    ctx.user_data['ssh_edit_days'] = days
    await q.message.edit_text(f"\u23f3 Choisis l'heure pour +{days}j :", reply_markup=_exp_time_kb("sshexp"))
    return SSH_W_EDIT_EXP

async def ssh_edit_exp_set_time(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    user = ctx.user_data.get('ssh_edit_user')
    if not user:
        await q.message.edit_text("Erreur : utilisateur inconnu.")
        return ConversationHandler.END
    days = ctx.user_data.get('ssh_edit_days', 1)
    ts = q.data.split("_")[-1]
    dt = datetime.now(vpn_manager.TZ) + timedelta(days=days)
    dt = dt.replace(hour=int(ts[:2]), minute=int(ts[2:]), second=0, microsecond=0)
    ok, msg = ssh_manager.update_user_field(user, "expires_at", dt.strftime("%Y-%m-%d %H:%M"))
    await q.message.edit_text(f"Expiration SSH de {user} : {msg}")
    return ConversationHandler.END

async def ssh_edit_exp_back(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    await q.message.edit_text("\u23f3 Choisis la durée avant expiration :", reply_markup=_exp_presets_kb("sshexp"))
    return SSH_W_EDIT_EXP

async def ssh_edit_exp_manual(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = upd.callback_query
    await q.answer()
    await q.message.reply_text("\u23f3 Entrez la **nouvelle date** au format `YYYY-MM-DD HH:MM`\nExemple : `2026-08-20 14:30`", parse_mode="Markdown")
    return SSH_W_EDIT_EXP

async def ssh_edit_exp_text(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ctx.user_data['ssh_edit_user']
    ok, msg = ssh_manager.update_user_field(user, "expires_at", upd.message.text.strip())
    await upd.message.reply_text(f"Expiration SSH de {user} : {msg}")
    return ConversationHandler.END

# --- END SSH CRM ---

async def alert_job(ctx: ContextTypes.DEFAULT_TYPE):
    # Check for expired users with precise time
    try:
        import vpn_manager
        exp_users = vpn_manager.get_expired_users()
        for eu in exp_users:
            vpn_manager.lock_user(eu)
            # Notify admin
            if chat_ids:
                for cid in list(chat_ids):
                    await ctx.bot.send_message(chat_id=cid, text=f"⚠️ Le compte VPN <b>{eu}</b> a expiré et a été verrouillé automatiquement.", parse_mode="HTML")
    except Exception as e:
        log.error(f"Error handling expired users: {e}")

    # Vérification comptes SSH expirés
    try:
        exp_ssh = ssh_manager.get_expired_users()
        for eu in exp_ssh:
            ssh_manager.lock_user(eu)
            if chat_ids:
                for cid in list(chat_ids):
                    await ctx.bot.send_message(
                        chat_id=cid,
                        text=f"⚠️ Le compte SSH <b>{eu}</b> a expiré et a été verrouillé.",
                        parse_mode="HTML"
                    )
    except Exception as e:
        log.error(f"Erreur SSH expirés: {e}")

    # Vérification quota data SSH
    try:
        conn = sqlite3.connect("ssh_accounts.db")
        c = conn.cursor()
        c.execute("SELECT username, data_limit_mb, data_used_mb FROM ssh_users WHERE data_limit_mb > 0")
        for row in c.fetchall():
            uname, dlim, dused = row
            ssh_manager.update_data_used(uname)
        conn.close()
        # Re-request with updated values
        conn = sqlite3.connect("ssh_accounts.db")
        c = conn.cursor()
        c.execute("SELECT username, data_limit_mb, data_used_mb FROM ssh_users WHERE data_limit_mb > 0")
        for row in c.fetchall():
            uname, dlim, dused = row
            if dused >= dlim:
                ssh_manager.lock_user(uname)
                if chat_ids:
                    for cid in list(chat_ids):
                        await ctx.bot.send_message(
                            chat_id=cid,
                            text=f"⚠️ Le compte SSH <b>{uname}</b> a atteint son quota data ({dused:.1f}/{dlim} MB) et a été verrouillé.",
                            parse_mode="HTML"
                        )
        conn.close()
    except Exception as e:
        log.error(f"Erreur SSH data quota: {e}")

    if not chat_ids:
        return
    alerts = []
    cpup = psutil.cpu_percent(interval=1)
    if cpup > 80:
        alerts.append(f"CPU a {cpup}%")
    mem = psutil.virtual_memory()
    if mem.percent > 85:
        alerts.append(f"RAM a {mem.percent}%")
    d = psutil.disk_usage("/")
    if d.percent > 85:
        alerts.append(f"Disque a {d.percent}%")
    if alerts:
        msg = "\U0001f6a8 ALERTES SERVEUR\n" + f"{'='*28}\n" + "\n".join(alerts)
        for cid in list(chat_ids):
            try:
                await ctx.bot.send_message(chat_id=cid, text=msg)
            except Exception:
                pass

async def refresh_callback(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = upd.callback_query
    await query.answer()
    if not is_authorized(upd.effective_chat.id):
        await query.message.reply_text("\u26d4 Acces refuse.")
        return
    cmd = query.data.replace("r_", "")
    builders = {
        "status": build_status,
        "system": build_system,
        "cpu": build_cpu,
        "ram": build_ram,
        "disk": build_disk,
        "gpu": build_gpu,
        "network": build_network,
    }
    builder = builders.get(cmd)
    if builder:
        try:
            await query.edit_message_text(builder(), reply_markup=refresh_btn(cmd))
        except Exception as e:
            log.warning(f"Refresh error: {e}")

def understand(text):
    t = text.lower().strip()
    if not t:
        return None

    patterns = {
        "status": [r"\b(?:tout|global|general|complet|tableau|bord|dashboard|resume|recap)\b",
                   r"\betat\b.*\bserveur\b", r"\bserveur\b.*\betat\b"],
        "cpu":    [r"\bcpu\b", r"\bprocesseur\b", r"\bcharge\b", r"\bprocesseur", r"processeur\b"],
        "ram":    [r"\bram\b", r"\bmemoire\b", r"\bmémoire\b", r"\bswap\b", r"\bm?emoire vive\b"],
        "disk":   [r"\bdisque\b", r"\bstockage\b", r"\bdd\b", r"\bssd\b", r"\bespace\b",
                   r"\bplace\b", r"\bsature\b", r"\bplein\b", r"\blibre\b"],
        "gpu":    [r"\bgpu\b", r"\bcarte graphique\b", r"\bnvidia\b", r"\bgraphique\b"],
        "network":[r"\breseau\b", r"\bréseau\b", r"\binternet\b", r"\bnetwork\b", r"\bnet\b",
                   r"\bdebit\b", r"\bdébit\b", r"\bconnexion\b", r"\bwifi\b", r"\beth?0\b"],
        "system": [r"\bsysteme\b", r"\bsystème\b", r"\bos\b", r"\bhostname\b", r"\binfo\b",
                   r"\bkernel\b", r"\bnoyau\b", r"\bconfiguration\b"],
    }

    scores = {}
    for cmd, pats in patterns.items():
        score = 0
        for pat in pats:
            matches = re.findall(pat, t)
            score += len(matches)
        if score > 0:
            scores[cmd] = score

    if not scores:
        return None
    return max(scores, key=scores.get)

def build_answer(cmd):
    builders = {
        "status": build_status,
        "system": build_system,
        "cpu": build_cpu,
        "ram": build_ram,
        "disk": build_disk,
        "gpu": build_gpu,
        "network": build_network,
    }
    fn = builders.get(cmd)
    if fn:
        return fn()
    return None

replies = {
    "cpu":    ["Voici l etat du CPU :"],
    "ram":    ["Voici la memoire RAM :"],
    "disk":   ["Voici le disque :"],
    "gpu":    ["Voici le GPU :"],
    "network":["Voici le reseau :"],
    "system": ["Voici les infos systeme :"],
    "status": ["Voici le tableau de bord complet :"],
}

def greet_reply():
    h = datetime.now().hour
    if h < 12: return "Bonjour"
    if h < 18: return "Bon apres-midi"
    return "Bonsoir"

async def chat_handler(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _req_auth(upd): return
    reg(upd.effective_chat.id)
    msg = upd.message.text.strip()

    if re.match(r"^(bonjour|salut|bonsoir|hey|coucou|hello|hi)\b", msg.lower()):
        await upd.message.reply_text(f"{greet_reply()} ! Je suis le bot de monitoring.\nTape /help pour voir les commandes, ou parle-moi en naturel.")
        return

    if re.match(r"^(merci|thanks|thx)\b", msg.lower()):
        await upd.message.reply_text("De rien ! A ta disposition.")
        return

    if re.match(r"^(au revoir|bye|a plus|adieu)\b", msg.lower()):
        await upd.message.reply_text("Au revoir ! Reviens quand tu veux.")
        return

    cmd = understand(msg)
    if cmd:
        data = build_answer(cmd)
        if data:
            intro = replies[cmd][0]
            await upd.message.reply_text(f"{intro}\n\n{data}", reply_markup=refresh_btn(cmd))
        else:
            await upd.message.reply_text("Desole, je n ai pas pu obtenir les donnees.")
    else:
        await upd.message.reply_text(
            "Je n ai pas compris. Tu peux me demander :\n"
            "- \"comment va le CPU ?\"\n"
            "- \"la RAM est pleine ?\"\n"
            "- \"le disque\"\n"
            "- \"le reseau\"\n"
            "- \"le GPU\"\n"
            "- \"les infos serveur\"\n"
            "- \"le tableau de bord\"\n"
            "Ou tape /help pour les commandes."
        )

async def post_init(app: Application):
    cmds = [
        BotCommand("start", "Demarrer le bot"),
        BotCommand("system", "Infos systeme"),
        BotCommand("status", "Resume complet"),
        BotCommand("cpu", "Utilisation CPU"),
        BotCommand("ram", "RAM et Swap"),
        BotCommand("disk", "Disque et I/O"),
        BotCommand("gpu", "GPU NVIDIA"),
        BotCommand("network", "Stats reseau"),
        BotCommand("vpn", "Gestion comptes ZiVPN"),
        BotCommand("ssh", "Gestion comptes SSH (Payload)"),
        BotCommand("grant", "Creer un code invite (admin)"),
        BotCommand("auth", "Se connecter avec un code invite"),
        BotCommand("help", "Aide"),
    ]
    await app.bot.set_my_commands(cmds)
    log.info("Commandes enregistrees OK")

def main():
    token = get_token()
    if not token:
        log.error("Token manquant. Cree .env_bot avec TELEGRAM_BOT_TOKEN=ton_token")
        return

    app = Application.builder().token(token).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("system", system))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("cpu", cpu))
    app.add_handler(CommandHandler("ram", ram))
    app.add_handler(CommandHandler("disk", disk))
    app.add_handler(CommandHandler("gpu", gpu))
    app.add_handler(CommandHandler("network", network))
    app.add_handler(CommandHandler("help", help))
    app.add_handler(CommandHandler("grant", grant))
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("vpn", vpn_menu))

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(vpn_cb, pattern="^vpn_new$"),
            CallbackQueryHandler(vpn_cb, pattern="^editpass_"),
            CallbackQueryHandler(vpn_cb, pattern="^editexp_")
        ],
        states={
            W_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, v_user)],
            W_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, v_pass)],
            W_DUR:  [
                CallbackQueryHandler(v_dur_preset, pattern="^dur_\\d+$"),
                CallbackQueryHandler(v_dur_set_time, pattern="^durt_\\d+$"),
                CallbackQueryHandler(v_dur_back, pattern="^durt_back$"),
                CallbackQueryHandler(v_dur_manual, pattern="^dur_manual$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, v_dur_text)
            ],
            W_EDIT_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_pass)],
            W_EDIT_EXP:  [
                CallbackQueryHandler(edit_exp_preset, pattern="^exp_\\d+$"),
                CallbackQueryHandler(edit_exp_set_time, pattern="^expt_\\d+$"),
                CallbackQueryHandler(edit_exp_back, pattern="^expt_back$"),
                CallbackQueryHandler(edit_exp_manual, pattern="^exp_manual$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_exp_text)
            ]
        },
        fallbacks=[CommandHandler("cancel", v_cancel)],
        per_message=False,
    )
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(vpn_cb, pattern="^vpn_|^vpninfo_"))

    # ── SSH CRM handlers ──
    app.add_handler(CommandHandler("ssh", ssh_menu))

    ssh_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(ssh_cb, pattern="^ssh_new$"),
                CallbackQueryHandler(ssh_cb, pattern="^ssheditpass_"),
                CallbackQueryHandler(ssh_cb, pattern="^ssheditexp_"),
            ],
            states={
                SSH_W_USER:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ssh_v_user)],
                SSH_W_PASS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ssh_v_pass)],
                SSH_W_DUR:      [
                    CallbackQueryHandler(ssh_v_dur_preset, pattern="^sshdur_\\d+$"),
                    CallbackQueryHandler(ssh_v_dur_set_time, pattern="^sshdurt_\\d+$"),
                    CallbackQueryHandler(ssh_v_dur_back, pattern="^sshdurt_back$"),
                    CallbackQueryHandler(ssh_v_dur_manual, pattern="^sshdur_manual$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, ssh_v_dur_text)
                ],
                SSH_W_CONN:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ssh_v_conn)],
                SSH_W_DATA:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ssh_v_data)],
                SSH_W_EDIT_PASS:[MessageHandler(filters.TEXT & ~filters.COMMAND, ssh_edit_pass)],
                SSH_W_EDIT_EXP: [
                    CallbackQueryHandler(ssh_edit_exp_preset, pattern="^sshexp_\\d+$"),
                    CallbackQueryHandler(ssh_edit_exp_set_time, pattern="^sshexpt_\\d+$"),
                    CallbackQueryHandler(ssh_edit_exp_back, pattern="^sshexpt_back$"),
                    CallbackQueryHandler(ssh_edit_exp_manual, pattern="^sshexp_manual$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, ssh_edit_exp_text)
                ],
            },
            fallbacks=[CommandHandler("cancel", v_cancel)],
            per_message=False,
        )
    app.add_handler(ssh_conv)
    app.add_handler(CallbackQueryHandler(ssh_cb, pattern="^ssh_|^sshinfo_|^sshdel_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))
    app.add_handler(CallbackQueryHandler(refresh_callback, pattern="^r_"))
    app.job_queue.run_repeating(alert_job, interval=60, first=30)
    log.info("Bot demarre...")
    app.run_polling()

if __name__ == "__main__":
    main()
