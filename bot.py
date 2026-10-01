import os, re, json, time, sqlite3
from html import escape
from urllib.request import Request, urlopen
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

DB_FILE = "alphascope.db"
TRACKER_CHANNEL = os.getenv("TRACKER_CHANNEL", "@AlphaScopeTracker")
CHECK_SECONDS = 60

CA_RE = re.compile(r"(?<![A-Za-z0-9])[1-9A-HJ-NP-Za-km-z]{32,44}(?![A-Za-z0-9])")
DEX_RE = re.compile(r"https?://(?:www\.)?dexscreener\.com/solana/([1-9A-HJ-NP-Za-km-z]{32,44})", re.I)
PUMP_RE = re.compile(r"https?://(?:www\.)?pump\.fun/coin/([1-9A-HJ-NP-Za-km-z]{32,44})", re.I)

def db():
    c = sqlite3.connect(DB_FILE)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.execute("CREATE TABLE IF NOT EXISTS channels(username TEXT PRIMARY KEY)")
    c.execute("""CREATE TABLE IF NOT EXISTS calls(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT, ca TEXT, name TEXT, symbol TEXT,
        initial_mc REAL, current_mc REAL, liquidity REAL, volume24 REAL,
        change24 REAL, first_seen INTEGER, last_update INTEGER,
        last_milestone INTEGER DEFAULT 1, UNIQUE(source,ca))""")
    seeds = [x.strip() for x in os.getenv("TRACKED_CHANNELS","").split(",") if x.strip()]
    for x in seeds:
        if not x.startswith("@"): x = "@"+x
        c.execute("INSERT OR IGNORE INTO channels VALUES (?)", (x.lower(),))
    c.commit()
    c.close()

def add_channel(ch):
    ch = ch.strip()
    if not ch.startswith("@"): ch = "@"+ch
    ch = ch.lower()
    c = db()
    c.execute("INSERT OR IGNORE INTO channels VALUES (?)", (ch,))
    c.commit()
    c.close()
    return ch

def tracked(ch):
    c = db()
    r = c.execute("SELECT 1 FROM channels WHERE lower(username)=lower(?)", (ch,)).fetchone()
    c.close()
    return r is not None

def channel_list():
    c = db()
    r = c.execute("SELECT username FROM channels ORDER BY username").fetchall()
    c.close()
    return [x["username"] for x in r]

def extract_ca(text):
    if not text:
        return None
    for rx in (DEX_RE, PUMP_RE):
        m = rx.search(text)
        if m:
            return m.group(1)
    m = CA_RE.search(text)
    return m.group(0) if m else None

def get_dex(ca):
    u = f"https://api.dexscreener.com/token-pairs/v1/solana/{ca}"
    req = Request(u, headers={"User-Agent":"AlphaScope/3.0","Accept":"application/json"})
    with urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    pairs = data if isinstance(data, list) else []
    if not pairs:
        return None

    p = max(pairs, key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0))
    base = p.get("baseToken") or {}
    info = p.get("info") or {}
    twitter = next((s.get("url") for s in info.get("socials") or [] if s.get("type") == "twitter"), None)

    return {
        "name": base.get("name") or "Unknown",
        "symbol": base.get("symbol") or "???",
        "mc": float(p.get("marketCap") or p.get("fdv") or 0),
        "liq": float((p.get("liquidity") or {}).get("usd") or 0),
        "vol": float((p.get("volume") or {}).get("h24") or 0),
        "change": float((p.get("priceChange") or {}).get("h24") or 0),
        "created": p.get("pairCreatedAt"),
        "chart": f"https://dexscreener.com/solana/{ca}",
        "twitter": twitter,
    }

def age(created):
    if not created:
        return "?"
    m = max(0, int((time.time()*1000-int(created))/60000))
    return f"{m//1440}d" if m >= 1440 else f"{m//60}h" if m >= 60 else f"{m}m"

def save_call(source, ca, d):
    now = int(time.time())
    c = db()
    old = c.execute("SELECT * FROM calls WHERE source=? AND ca=?", (source, ca)).fetchone()

    if old:
        c.execute("""UPDATE calls SET current_mc=?,liquidity=?,volume24=?,change24=?,
                     name=?,symbol=?,last_update=? WHERE id=?""",
                  (d["mc"],d["liq"],d["vol"],d["change"],d["name"],d["symbol"],now,old["id"]))
        initial = old["initial_mc"]
        cid = old["id"]
    else:
        c.execute("""INSERT INTO calls(source,ca,name,symbol,initial_mc,current_mc,liquidity,volume24,
                     change24,first_seen,last_update,last_milestone)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,1)""",
                  (source,ca,d["name"],d["symbol"],d["mc"],d["mc"],d["liq"],d["vol"],d["change"],now,now))
        cid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        initial = d["mc"]

    c.commit()
    c.close()
    return cid, initial

def refresh(cid, d):
    c = db()
    c.execute("""UPDATE calls SET current_mc=?,liquidity=?,volume24=?,change24=?,
                 name=?,symbol=?,last_update=? WHERE id=?""",
              (d["mc"],d["liq"],d["vol"],d["change"],d["name"],d["symbol"],int(time.time()),cid))
    c.commit()
    c.close()

def milestone(cid, m):
    c = db()
    c.execute("UPDATE calls SET last_milestone=? WHERE id=?", (m,cid))
    c.commit()
    c.close()

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 Live Calls",callback_data="live"),
         InlineKeyboardButton("📡 Track Channel",callback_data="track")],
        [InlineKeyboardButton("📊 Analyse",callback_data="analyse"),
         InlineKeyboardButton("🏆 Top KOLs",callback_data="top")],
        [InlineKeyboardButton("📈 Performance",callback_data="performance"),
         InlineKeyboardButton("ℹ️ About",callback_data="about")]])

def buttons(d):
    row = [InlineKeyboardButton("📊 Chart",url=d["chart"])]
    if d.get("twitter"):
        row.append(InlineKeyboardButton("🐦 Twitter",url=d["twitter"]))
    return InlineKeyboardMarkup([row])

def post_text(source, ca, d, initial, m=None):
    x = d["mc"]/initial if initial > 0 else 1
    badge = "🚀 10X+" if x >= 10 else "🔥 5X+" if x >= 5 else "💎 3X+" if x >= 3 else "🚀 2X+" if x >= 2 else "🟢 LIVE"
    alert = f"\n\n🎯 <b>MILESTONE: {m}X</b>" if m else ""
    title = "MILESTONE UPDATE" if m else "NEW KOL CALL"
    return (f"⚡ <b>{title}</b>\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"📡 <b>Source:</b> {escape(source)}\n"
            f"🪙 <b>{escape(d['name'])}</b> - ${escape(d['symbol'])}\n\n"
            f"🧾 <b>Solana CA:</b>\n<code>{escape(ca)}</code>\n\n"
            f"🌱 Age: <b>{age(d.get('created'))}</b>\n"
            f"💰 MC: <b>${d['mc']:,.2f}</b>\n"
            f"💧 Liq: <b>${d['liq']:,.2f}</b>\n"
            f"📈 24h: <b>{d['change']:.2f}%</b>\n"
            f"📦 Vol: <b>${d['vol']:,.2f}</b>\n"
            f"📊 Multiple: <b>{x:.2f}X</b> {badge}{alert}\n\n"
            f"━━━━━━━━━━━━━━━━\n⚡ <b>AlphaScope Tracker</b>")

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting"] = False
    await update.message.reply_text(
        "⚡ <b>AlphaScope</b>\n\nKOL calls + live MC + 2X/3X/5X/10X alerts.",
        parse_mode="HTML", reply_markup=menu())

async def help_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start\n/track @channel\n/channels\n/help")

async def track_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use: /track @channel")
    ch = add_channel(context.args[0])
    await update.message.reply_text(f"✅ Tracking enabled: {ch}\nBot must be admin there.")

async def channels_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    xs = channel_list()
    await update.message.reply_text("📡 Tracked:\n\n" + ("\n".join("• "+x for x in xs) if xs else "None"))

async def text_input(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting"):
        return
    ch = update.message.text.strip()
    if not ch.startswith("@"):
        return await update.message.reply_text("Send @channelusername")
    ch = add_channel(ch)
    context.user_data["waiting"] = False
    await update.message.reply_text(
        f"✅ {ch} added.\nNew CA posts will be analysed.", reply_markup=menu())

async def callback(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "track":
        context.user_data["waiting"] = True
        return await q.edit_message_text(
            "📡 <b>Track Channel</b>\n\nSend: <code>@channelusername</code>\n\nBot must be admin.",
            parse_mode="HTML")

    if q.data == "live":
        c = db()
        rows = c.execute("SELECT * FROM calls ORDER BY last_update DESC LIMIT 10").fetchall()
        c.close()
        if not rows:
            text = "🔥 <b>Live Calls</b>\n\nNo calls yet."
        else:
            text = "🔥 <b>Live Calls</b>\n\n"
            for r in rows:
                x = r["current_mc"]/r["initial_mc"] if r["initial_mc"] else 1
                text += (f"🪙 <b>{escape(r['name'] or 'Unknown')}</b> "
                         f"${escape(r['symbol'] or '???')} — ${r['current_mc']:,.0f} — <b>{x:.2f}X</b>\n"
                         f"📡 {escape(r['source'])}\n\n")
        return await q.edit_message_text(
            text,parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main",callback_data="home")]]))

    if q.data == "analyse":
        c = db()
        rows = c.execute("SELECT * FROM calls ORDER BY current_mc DESC LIMIT 10").fetchall()
        c.close()
        text = "📊 <b>Analyse</b>\n\n"
        if not rows:
            text += "No calls yet."
        for r in rows:
            x = r["current_mc"]/r["initial_mc"] if r["initial_mc"] else 1
            text += (f"🪙 <b>{escape(r['name'] or 'Unknown')}</b> ${escape(r['symbol'] or '???')}\n"
                     f"Start MC: ${r['initial_mc']:,.0f}\n"
                     f"Current MC: ${r['current_mc']:,.0f}\n"
                     f"Result: <b>{x:.2f}X</b>\n"
                     f"24h: {r['change24']:.2f}%\n\n")
        return await q.edit_message_text(
            text,parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main",callback_data="home")]]))

    if q.data == "performance":
        text = ("📈 <b>Performance</b>\n\n"
                "Initial MC is saved at the KOL call. Current MC is checked every 60 seconds.\n"
                "Milestones: 2X → 3X → 5X → 10X → 20X → 50X → 100X.")
    elif q.data == "top":
        text = "🏆 <b>Top KOLs</b>\n\nLeaderboard calculation can be added after enough calls are stored."
    elif q.data == "about":
        text = "ℹ️ <b>AlphaScope</b>\n\nDetects Solana CAs, gets DexScreener market data, posts formatted calls and monitors MC multiples."
    else:
        return await q.edit_message_text(
            "⚡ <b>AlphaScope</b>\n\nChoose an option:",
            parse_mode="HTML", reply_markup=menu())

    await q.edit_message_text(
        text,parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main",callback_data="home")]]))

async def channel_post(update:Update, context:ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg or not msg.chat.username:
        return

    source = "@" + msg.chat.username
    print("📥 CHANNEL POST:",source,msg.message_id)

    if not tracked(source):
        print("⏭️ NOT TRACKED:",source)
        return

    text = (msg.text or msg.caption or "").strip()
    ca = extract_ca(text)

    if not ca:
        print("⚠️ NO CA:",source)
        return

    try:
        d = get_dex(ca)
        if not d or d["mc"] <= 0:
            print("⚠️ NO DEX DATA:",ca)
            return

        _, initial = save_call(source,ca,d)

        await context.bot.send_message(
            chat_id=TRACKER_CHANNEL,
            text=post_text(source,ca,d,initial),
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=buttons(d))
        print("✅ POSTED:",ca)

    except Exception as e:
        print("❌ POST ERROR:",repr(e))

async def monitor(context:ContextTypes.DEFAULT_TYPE):
    c = db()
    rows = c.execute("SELECT * FROM calls ORDER BY last_update DESC LIMIT 100").fetchall()
    c.close()

    for r in rows:
        try:
            d = get_dex(r["ca"])
            if not d or d["mc"] <= 0 or r["initial_mc"] <= 0:
                continue

            x = d["mc"]/r["initial_mc"]
            old = int(r["last_milestone"] or 1)
            reached = [m for m in (2,3,5,10,20,50,100) if x >= m and m > old]
            refresh(r["id"],d)

            for m in reached:
                milestone(r["id"],m)
                await context.bot.send_message(
                    chat_id=TRACKER_CHANNEL,
                    text=post_text(r["source"],r["ca"],d,r["initial_mc"],m),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=buttons(d))
                print(f"🚀 {r['symbol']} {m}X")

        except Exception as e:
            print("❌ MONITOR:",r["ca"],repr(e))

async def post_init(app:Application):
    init_db()
    if app.job_queue:
        app.job_queue.run_repeating(monitor,interval=CHECK_SECONDS,first=15,name="mc-monitor")
    print("🚀 AlphaScope started")

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN secret is missing")

    app = Application.builder().token(token).post_init(post_init).build()

    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("help",help_cmd))
    app.add_handler(CommandHandler("track",track_cmd))
    app.add_handler(CommandHandler("channels",channels_cmd))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_input))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST,channel_post))

    app.run_polling(allowed_updates=Update.ALL_TYPES,drop_pending_updates=False)

if __name__ == "__main__":
    main()
