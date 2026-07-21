import os, json, logging, time, platform, subprocess, re
from datetime import datetime
from pathlib import Path

import psutil
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import vpn_manager

BASE_DIR = Path(__file__).parent.resolve()
CHAT_ID_FILE = BASE_DIR / ".bot_chat_ids.json"
ENV_FILE = BASE_DIR / ".env_bot"

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
    reg(upd.effective_chat.id)
    await upd.message.reply_text(
        "\U0001f916 Monitoring Bot\n"
        f"{'='*28}\n"
        "\U0001f4a1 Surveillance materiel en temps reel\n"
        "\U0001f447 Tape / pour voir les commandes\n"
        "\U0001f514 Alertes automatiques si seuil depasse"
    )

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
    reg(upd.effective_chat.id)
    await upd.message.reply_text(build_network(), reply_markup=refresh_btn("network"))

async def help(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    reg(upd.effective_chat.id)
    await upd.message.reply_text(
        "\U0001f916 Commandes disponibles\n"
        f"{'='*28}\n"
        "\U0001f4ca /status - Resume complet\n"
        "\U0001f5a5 /system - Infos systeme\n"
        "\U0001f5a5 /cpu    - Utilisation CPU\n"
        "\U0001f9e0 /ram    - RAM et Swap\n"
        "\U0001f4be /disk   - Disque et I/O\n"
        "\U0001f3ae /gpu    - GPU NVIDIA\n"
        "\U0001f4e1 /network- Stats reseau\n"
        "/help   - Cette aide\n"
        "\n"
        "\U0001f514 Seuils d'alerte: CPU>80%, RAM>85%, Disque>85%"
    )

# --- VPN CRM LOGIC ---
W_USER, W_PASS, W_DUR, W_LIM = range(4)

async def vpn_menu(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
            out = "📋 <b>Comptes VPN</b>\n\n"
            for u, p, exp, lim in rows:
                out += f"👤 <b>{u}</b> (Pass: {p})\n⏳ Expire : {exp}\n📊 Limite : {lim} Go\n---\n"
            await q.message.reply_text(out, parse_mode="HTML")
        return ConversationHandler.END

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
    await upd.message.reply_text("⏳ Entrez la **durée en jours** (ex: 30) :", parse_mode="Markdown")
    return W_DUR

async def v_dur(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data['v_dur'] = int(upd.message.text.strip())
        kb = [
            [InlineKeyboardButton("📦 Entrer en Mo (Mégaoctets)", callback_data="lim_mo")],
            [InlineKeyboardButton("💾 Entrer en Go (Gigaoctets)", callback_data="lim_go")],
            [InlineKeyboardButton("♾ Illimité", callback_data="lim_inf")],
        ]
        await upd.message.reply_text("📊 Quelle est l'unité de la limite de données ?", reply_markup=InlineKeyboardMarkup(kb))
        return W_LIM
    except:
        await upd.message.reply_text("Veuillez entrer un nombre entier valide pour la durée.")
        return W_DUR

async def v_lim_unit(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Callback quand l'user choisit Mo/Go/Illimité"""
    q = upd.callback_query
    await q.answer()
    unit = q.data  # lim_mo / lim_go / lim_inf
    if unit == "lim_inf":
        ctx.user_data['v_lim'] = 0
        ctx.user_data['v_lim_unit'] = "Illimité"
        return await _create_account(upd, ctx)
    else:
        ctx.user_data['v_lim_unit'] = "Mo" if unit == "lim_mo" else "Go"
        label = "Mo (Mégaoctets)" if unit == "lim_mo" else "Go (Gigaoctets)"
        await q.message.reply_text(f"📊 Entrez la valeur de la limite en **{label}** (ex: 500) :", parse_mode="Markdown")
        return W_LIM

async def v_lim(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data['v_lim'] = float(upd.message.text.strip())
        return await _create_account(upd, ctx)
    except:
        await upd.message.reply_text("Veuillez entrer un nombre valide pour la limite.")
        return W_LIM

async def _create_account(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = ctx.user_data['v_user']
    p = ctx.user_data['v_pass']
    d = ctx.user_data['v_dur']
    l = ctx.user_data['v_lim']
    unit = ctx.user_data.get('v_lim_unit', 'Go')
    # Convert to MB for storage
    l_mb = 0 if unit == 'Illimité' else (l if unit == 'Mo' else l * 1024)

    msg_obj = upd.message or upd.callback_query.message
    await msg_obj.reply_text("⏳ Création du compte en cours sur le serveur...")
    ok, msg = vpn_manager.add_user(u, p, d, l_mb)

    if ok:
        import urllib.request
        ip = "127.0.0.1"
        try: ip = urllib.request.urlopen("https://api.ipify.org").read().decode('utf8')
        except: pass

        quota_str = "Illimité" if l_mb == 0 else f"{l} {unit}"
        res = (
            f"🟢 <b>Compte VPN Créé avec Succès !</b>\n\n"
            f"🌐 <b>Host / IP</b> : <code>{ip}</code>\n"
            f"🔌 <b>Port UDP</b> : <code>443</code>\n"
            f"👤 <b>User</b> : <code>{u}</code>\n"
            f"🔑 <b>Pass</b> : <code>{p}</code>\n"
            f"⏳ <b>Durée</b> : {d} jours\n"
            f"📊 <b>Quota</b> : {quota_str}\n"
        )
        await msg_obj.reply_text(res, parse_mode="HTML")
    else:
        await msg_obj.reply_text(f"❌ Erreur lors de la création : {msg}")
    return ConversationHandler.END

async def v_cancel(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await upd.message.reply_text("Création annulée.")
    return ConversationHandler.END

# --- END VPN CRM ---

async def alert_job(ctx: ContextTypes.DEFAULT_TYPE):
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
    app.add_handler(CommandHandler("vpn", vpn_menu))

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(vpn_cb, pattern="^vpn_new$")],
        states={
            W_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, v_user)],
            W_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, v_pass)],
            W_DUR:  [MessageHandler(filters.TEXT & ~filters.COMMAND, v_dur)],
            W_LIM:  [
                CallbackQueryHandler(v_lim_unit, pattern="^lim_(mo|go|inf)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, v_lim),
            ],
        },
        fallbacks=[CommandHandler("cancel", v_cancel)],
        per_message=False,
    )
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(vpn_cb, pattern="^vpn_"))


    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))
    app.add_handler(CallbackQueryHandler(refresh_callback, pattern="^r_"))
    app.job_queue.run_repeating(alert_job, interval=60, first=30)
    log.info("Bot demarre...")
    app.run_polling()

if __name__ == "__main__":
    main()
