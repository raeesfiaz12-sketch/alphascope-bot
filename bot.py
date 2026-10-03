import os
import re
import json
import time
import sqlite3
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TRACKER_CHANNEL = os.getenv("TRACKER_CHANNEL", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "alphascope.db"
CHECK_SECONDS = 60

# Alerts happen at these multipliers.
MILESTONES = [2, 3, 5, 10, 20, 50, 100, 200, 500, 1000]

CA_RE = re.compile(
    r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b"
)

DEX_RE = re.compile(
    r"https?://(?:www\.)?dexscreener\.com/solana/([1-9A-HJ-NP-Za-km-z]{32,44})",
    re.I,
)

PUMP_RE = re.compile(
    r"https?://(?:www\.)?pump\.fun/coin/([1-9A-HJ-NP-Za-km-z]{32,44})",
    re.I,
)

WAITING = {}


# =========================================================
# DATABASE
# =========================================================

def db():
    c = sqlite3.connect(DB_FILE)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = db()

    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            username TEXT PRIMARY KEY,
            title TEXT,
            added_by INTEGER,
            added_at INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            requester INTEGER,
            status TEXT DEFAULT 'pending',
            created_at INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            source_title TEXT,
            message_id INTEGER,
            post_link TEXT,
            ca TEXT,
            name TEXT,
            symbol TEXT,
            initial_mc REAL,
            current_mc REAL,
            first_seen INTEGER,
            last_update INTEGER,
            last_milestone REAL DEFAULT 1,
            milestones TEXT DEFAULT '[]'
        )
    """)

    c.commit()
    c.close()


# =========================================================
# HELPERS
# =========================================================

def normalize_channel(value):
    value = value.strip()

    if value.startswith("https://t.me/"):
        path = urlparse(value).path.strip("/")
        if "/" in path:
            path = path.split("/")[0]
        value = path

    if value.startswith("http://t.me/"):
        path = urlparse(value).path.strip("/")
        if "/" in path:
            path = path.split("/")[0]
        value = path

    if not value.startswith("@"):
        value = "@" + value

    return value.lower()


def extract_ca(text):
    if not text:
        return None

    for rx in (DEX_RE, PUMP_RE):
        m = rx.search(text)
        if m:
            return m.group(1)

    m = CA_RE.search(text)
    return m.group(0) if m else None


def money(x):
    try:
        x = float(x)

        if x >= 1_000_000_000:
            return f"${x / 1_000_000_000:.2f}B"

        if x >= 1_000_000:
            return f"${x / 1_000_000:.2f}M"

        if x >= 1_000:
            return f"${x / 1_000:.1f}K"

        return f"${x:.2f}"
    except Exception:
        return "$0"


def age_text(ts):
    try:
        mins = max(0, int((time.time() - int(ts)) / 60))

        if mins < 60:
            return f"{mins}m"

        if mins < 1440:
            return f"{mins // 60}h"

        return f"{mins // 1440}d"
    except Exception:
        return "?"


def post_link(source, message_id):
    username = source.replace("@", "").strip()

    if username:
        return f"https://t.me/{username}/{message_id}"

    return ""


def get_dex(ca):
    url = f"https://api.dexscreener.com/token-pairs/v1/solana/{ca}"

    req = Request(
        url,
        headers={
            "User-Agent": "AlphaScope/1.0",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return None

    pairs = data if isinstance(data, list) else []

    if not pairs:
        return None

    p = max(
        pairs,
        key=lambda x: float(
            (x.get("liquidity") or {}).get("usd") or 0
        ),
    )

    base = p.get("baseToken") or {}
    info = p.get("info") or {}

    socials = info.get("socials") or []

    twitter = next(
        (
            s.get("url")
            for s in socials
            if s.get("type") == "twitter"
        ),
        None,
    )

    try:
        mc = float(p.get("marketCap") or p.get("fdv") or 0)
    except Exception:
        mc = 0

    try:
        liquidity = float(
            (p.get("liquidity") or {}).get("usd") or 0
        )
    except Exception:
        liquidity = 0

    try:
        volume = float(
            (p.get("volume") or {}).get("h24") or 0
        )
    except Exception:
        volume = 0

    try:
        change = float(
            (p.get("priceChange") or {}).get("h24") or 0
        )
    except Exception:
        change = 0

    return {
        "name": base.get("name") or "Unknown",
        "symbol": base.get("symbol") or "???",
        "mc": mc,
        "liquidity": liquidity,
        "volume": volume,
        "change": change,
        "created": p.get("pairCreatedAt"),
        "twitter": twitter,
        "chart": f"https://dexscreener.com/solana/{ca}",
    }


# =========================================================
# CHANNEL MANAGEMENT
# =========================================================

def add_channel(username, title="", added_by=0):
    username = normalize_channel(username)

    c = db()

    c.execute(
        """
        INSERT OR IGNORE INTO channels
        (username, title, added_by, added_at)
        VALUES (?, ?, ?, ?)
        """,
        (username, title, added_by, int(time.time())),
    )

    c.commit()
    c.close()

    return username


def remove_channel(username):
    username = normalize_channel(username)

    c = db()
    c.execute(
        "DELETE FROM channels WHERE username=?",
        (username,),
    )
    c.commit()
    c.close()


def channel_exists(username):
    username = normalize_channel(username)

    c = db()
    row = c.execute(
        "SELECT 1 FROM channels WHERE lower(username)=lower(?)",
        (username,),
    ).fetchone()
    c.close()

    return row is not None


def channel_list():
    c = db()

    rows = c.execute(
        "SELECT username, title FROM channels ORDER BY username"
    ).fetchall()

    c.close()

    return rows


# =========================================================
# KOL REQUEST SYSTEM
# =========================================================

def create_request(username, requester):
    username = normalize_channel(username)

    c = db()

    existing = c.execute(
        """
        SELECT id, status
        FROM requests
        WHERE lower(username)=lower(?)
        AND status='pending'
        """,
        (username,),
    ).fetchone()

    if existing:
        c.close()
        return None

    cur = c.execute(
        """
        INSERT INTO requests
        (username, requester, status, created_at)
        VALUES (?, ?, 'pending', ?)
        """,
        (username, requester, int(time.time())),
    )

    request_id = cur.lastrowid

    c.commit()
    c.close()

    return request_id


def approve_request(request_id):
    c = db()

    row = c.execute(
        "SELECT * FROM requests WHERE id=?",
        (request_id,),
    ).fetchone()

    if not row:
        c.close()
        return None

    c.execute(
        "UPDATE requests SET status='approved' WHERE id=?",
        (request_id,),
    )

    c.execute(
        """
        INSERT OR IGNORE INTO channels
        (username, title, added_by, added_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            row["username"],
            row["username"],
            row["requester"],
            int(time.time()),
        ),
    )

    c.commit()
    c.close()

    return row


def reject_request(request_id):
    c = db()

    row = c.execute(
        "SELECT * FROM requests WHERE id=?",
        (request_id,),
    ).fetchone()

    if row:
        c.execute(
            "UPDATE requests SET status='rejected' WHERE id=?",
            (request_id,),
        )
        c.commit()

    c.close()

    return row


# =========================================================
# CALL DATABASE
# =========================================================

def save_call(source, source_title, message_id, link, ca, d):
    now = int(time.time())

    c = db()

    old = c.execute(
        """
        SELECT *
        FROM calls
        WHERE source=? AND ca=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (source, ca),
    ).fetchone()

    if old:
        c.execute(
            """
            UPDATE calls
            SET current_mc=?, last_update=?
            WHERE id=?
            """,
            (d["mc"], now, old["id"]),
        )

        call_id = old["id"]
        initial = old["initial_mc"]

    else:
        c.execute(
            """
            INSERT INTO calls
            (
                source,
                source_title,
                message_id,
                post_link,
                ca,
                name,
                symbol,
                initial_mc,
                current_mc,
                first_seen,
                last_update
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                source_title,
                message_id,
                link,
                ca,
                d["name"],
                d["symbol"],
                d["mc"],
                d["mc"],
                now,
                now,
            ),
        )

        call_id = c.execute(
            "SELECT last_insert_rowid()"
        ).fetchone()[0]

        initial = d["mc"]

    c.commit()
    c.close()

    return call_id, initial


def refresh_call(call_id, d):
    c = db()

    c.execute(
        """
        UPDATE calls
        SET current_mc=?, last_update=?
        WHERE id=?
        """,
        (d["mc"], int(time.time()), call_id),
    )

    c.commit()
    c.close()


def get_call(call_id):
    c = db()

    row = c.execute(
        "SELECT * FROM calls WHERE id=?",
        (call_id,),
    ).fetchone()

    c.close()

    return row


def mark_milestone(call_id, milestone):
    c = db()

    row = c.execute(
        "SELECT milestones FROM calls WHERE id=?",
        (call_id,),
    ).fetchone()

    if not row:
        c.close()
        return False

    try:
        done = json.loads(row["milestones"] or "[]")
    except Exception:
        done = []

    if milestone in done:
        c.close()
        return False

    done.append(milestone)

    c.execute(
        """
        UPDATE calls
        SET milestones=?, last_milestone=?
        WHERE id=?
        """,
        (json.dumps(done), milestone, call_id),
    )

    c.commit()
    c.close()

    return True


# =========================================================
# KOL STATS
# =========================================================

def kol_stats(source):
    c = db()

    rows = c.execute(
        """
        SELECT *
        FROM calls
        WHERE source=?
        ORDER BY first_seen DESC
        """,
        (source,),
    ).fetchall()

    c.close()

    if not rows:
        return None

    multipliers = []

    for r in rows:
        if r["initial_mc"] and r["initial_mc"] > 0:
            multipliers.append(
                max(
                    1,
                    r["current_mc"] / r["initial_mc"]
                )
            )

    avg_x = (
        sum(multipliers) / len(multipliers)
        if multipliers else 1
    )

    best = max(multipliers) if multipliers else 1

    hits = {
        2: 0,
        10: 0,
        100: 0,
        1000: 0,
    }

    for x in multipliers:
        if x >= 2:
            hits[2] += 1
        if x >= 10:
            hits[10] += 1
        if x >= 100:
            hits[100] += 1
        if x >= 1000:
            hits[1000] += 1

    return {
        "total": len(rows),
        "avg_x": avg_x,
        "best": best,
        "hits": hits,
        "last": rows[:6],
    }


def kolscope_text(source):
    stats = kol_stats(source)

    if not stats:
        return ""

    score = min(
        100,
        int(
            (
                min(stats["avg_x"], 10) / 10
            ) * 70
            + min(stats["total"], 100) / 100 * 30
        ),
    )

    filled = round(score / 10)
    bar = "🟢" * filled + "⚪" * (10 - filled)

    text = (
        "\n\n💍 <b>KOLscope STATS</b>\n\n"
        f"Channel: {source}\n"
        "Rank: Unranked\n\n"
        f"KOL SCORE: {score}%\n\n"
        f"{bar}\n\n"
        f"💵 Average X Per Call: {stats['avg_x']:.1f}x\n"
        f"💎 Total Calls: {stats['total']}\n"
        f"👑 Best Call: {stats['best']:.1f}x\n\n"
        "Last 6 Calls:\n"
    )

    for r in stats["last"]:
        if r["initial_mc"] > 0:
            x = max(
                1,
                r["current_mc"] / r["initial_mc"]
            )
        else:
            x = 1

        text += (
            f"\n💰 {r['symbol']}\n"
            f"     Multiplier: {x:.1f}x\n"
            f"     Call: {money(r['initial_mc'])} → "
            f"{money(r['current_mc'])}\n"
            f"     Age: {age_text(r['first_seen'])}\n"
        )

    text += (
        "\n───────────────────────\n\n"
        f"├🎯 Amount of 2x Hits: {stats['hits'][2]}\n"
        f"├🎯 Amount of 10x Hits: {stats['hits'][10]}\n"
        f"├🎯 Amount of 100x Hits: {stats['hits'][100]}\n"
        f"└🎯 Amount of 1000x Hits: {stats['hits'][1000]}"
    )

    return text


# =========================================================
# POST FORMAT
# =========================================================

def alert_text(row, d, multiplier, milestone):
    source = row["source"]

    link_button = []

    if row["post_link"]:
        link_button.append(
            InlineKeyboardButton(
                "🔎 Call",
                url=row["post_link"],
            )
        )

    link_button.append(
        InlineKeyboardButton(
            "📊 Chart",
            url=d["chart"],
        )
    )

    if d.get("twitter"):
        link_button.append(
            InlineKeyboardButton(
                "🐦 Twitter",
                url=d["twitter"],
            )
        )

    keyboard = InlineKeyboardMarkup(
        [link_button]
    )

    title = (
        f"🟪 <b>MULTIPLIER DETECTED: "
        f"{milestone}x+</b>\n\n"
    )

    text = (
        title
        + f"<b>{source}</b> made "
        f"<b>{multiplier:.1f}x+</b> on "
        f"<b>{d['symbol']}</b>.\n\n"
        f"{money(row['initial_mc'])} ⮕ "
        f"{money(d['mc'])}\n\n"
        "🔎 Call ❕💍 KOL\n"
        f"🪙 {d['name']} - ${d['symbol']}\n\n"
        f"🌱 Age: {age_text(d.get('created') or int(time.time()))}\n"
        f"💰 MC: {money(d['mc'])}\n"
        f"💧 Liq: {money(d['liquidity'])}\n"
        f"📈 24h: {d['change']:.2f}%\n"
        f"📦 Vol: {money(d['volume'])}\n"
        f"📊 Multiple: {multiplier:.2f}x 🟢 LIVE"
    )

    text += kolscope_text(source)

    return text, keyboard


# =========================================================
# COMMANDS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ List My Channel",
                callback_data="list_channel"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Tracking Channels",
                callback_data="channels"
            )
        ],
    ])

    await update.message.reply_text(
        "⚡ <b>AlphaScope Tracker</b>\n\n"
        "Track KOL calls and multiplier milestones.\n\n"
        "Use <b>List My Channel</b> to submit a channel "
        "for admin approval.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>Commands</b>\n\n"
        "/start - Main menu\n"
        "/track @channel - Admin add channel\n"
        "/untrack @channel - Admin remove channel\n"
        "/channels - Show tracked channels\n"
        "/requests - Show pending requests",
        parse_mode="HTML",
    )


async def track_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "Use: /track @channel"
        )
        return

    ch = add_channel(
        context.args[0],
        context.args[0],
        ADMIN_ID,
    )

    await update.message.reply_text(
        f"✅ Tracking enabled: {ch}"
    )


async def untrack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "Use: /untrack @channel"
        )
        return

    ch = normalize_channel(context.args[0])

    remove_channel(ch)

    await update.message.reply_text(
        f"🗑 Removed: {ch}"
    )


async def channels_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    rows = channel_list()

    if not rows:
        await update.message.reply_text(
            "No channels are currently tracked."
        )
        return

    text = "<b>📋 Tracking Channels</b>\n\n"

    for i, r in enumerate(rows, 1):
        text += f"{i}. {r['username']}\n"

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


async def requests_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    c = db()

    rows = c.execute(
        """
        SELECT *
        FROM requests
        WHERE status='pending'
        ORDER BY created_at DESC
        """
    ).fetchall()

    c.close()

    if not rows:
        await update.message.reply_text(
            "✅ No pending channel requests."
        )
        return

    for r in rows:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Accept",
                    callback_data=f"approve:{r['id']}",
                ),
                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data=f"reject:{r['id']}",
                ),
            ]
        ])

        await update.message.reply_text(
            f"📥 <b>New Channel Request</b>\n\n"
            f"Channel: {r['username']}\n"
            f"User ID: <code>{r['requester']}</code>",
            parse_mode="HTML",
            reply_markup=keyboard,
        )


# =========================================================
# TEXT INPUT
# =========================================================

async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if WAITING.get(user_id) != "channel":
        return

    text = (update.message.text or "").strip()

    if not text:
        return

    username = normalize_channel(text)

    WAITING.pop(user_id, None)

    request_id = create_request(
        username,
        user_id,
    )

    if not request_id:
        await update.message.reply_text(
            "⚠️ This channel already has a pending request."
        )
        return

    await update.message.reply_text(
        f"📨 Request submitted for <b>{username}</b>.\n\n"
        "⏳ Waiting for admin approval.",
        parse_mode="HTML",
    )

    if ADMIN_ID:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Accept",
                    callback_data=f"approve:{request_id}",
                ),
                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data=f"reject:{request_id}",
                ),
            ]
        ])

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "📥 <b>NEW CHANNEL REQUEST</b>\n\n"
                    f"Channel: <b>{username}</b>\n"
                    f"User ID: <code>{user_id}</code>\n\n"
                    "Approve this channel?"
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except Exception as e:
            print("ADMIN REQUEST ERROR:", e)


# =========================================================
# CALLBACKS
# =========================================================

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query

    await q.answer()

    data = q.data

    if data == "list_channel":
        WAITING[q.from_user.id] = "channel"

        await q.message.reply_text(
            "📡 <b>List My Channel</b>\n\n"
            "Send your public Telegram channel username "
            "or link.\n\n"
            "Example:\n"
            "<code>@ExampleChannel</code>\n\n"
            "⚠️ The bot must be added to the channel "
            "with permission to read posts.",
            parse_mode="HTML",
        )
        return

    if data == "channels":
        rows = channel_list()

        if not rows:
            await q.message.reply_text(
                "No channels are currently tracked."
            )
            return

        text = "<b>📋 Tracking Channels</b>\n\n"

        for i, r in enumerate(rows, 1):
            text += f"{i}. {r['username']}\n"

        await q.message.reply_text(
            text,
            parse_mode="HTML",
        )
        return

    if data.startswith("approve:"):
        if q.from_user.id != ADMIN_ID:
            return

        request_id = int(data.split(":")[1])

        row = approve_request(request_id)

        if not row:
            return

        await q.edit_message_text(
            f"✅ <b>APPROVED</b>\n\n"
            f"{row['username']} is now permanently tracked.",
            parse_mode="HTML",
        )

        try:
            await context.bot.send_message(
                chat_id=row["requester"],
                text=(
                    "✅ <b>Channel Approved</b>\n\n"
                    f"{row['username']} has been added "
                    "to AlphaScope tracking."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

        return

    if data.startswith("reject:"):
        if q.from_user.id != ADMIN_ID:
            return

        request_id = int(data.split(":")[1])

        row = reject_request(request_id)

        if not row:
            return

        await q.edit_message_text(
            f"❌ <b>REJECTED</b>\n\n"
            f"{row['username']} was not added.",
            parse_mode="HTML",
        )

        try:
            await context.bot.send_message(
                chat_id=row["requester"],
                text=(
                    "❌ <b>Channel Request Rejected</b>\n\n"
                    f"{row['username']} was not approved."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass


# =========================================================
# CHANNEL POST TRACKING
# =========================================================

async def channel_post(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    msg = update.channel_post

    if not msg:
        return

    username = (
        f"@{msg.chat.username}"
        if msg.chat.username
        else str(msg.chat.id)
    )

    username = username.lower()

    if not channel_exists(username):
        print("NOT TRACKED:", username)
        return

    text = (
        msg.text
        or msg.caption
        or ""
    ).strip()

    ca = extract_ca(text)

    if not ca:
        print("NO CA:", username)
        return

    try:
        d = get_dex(ca)

        if not d or d["mc"] <= 0:
            print("NO DEX DATA:", ca)
            return

        source_title = msg.chat.title or username

        link = post_link(
            username,
            msg.message_id,
        )

        call_id, initial = save_call(
            username,
            source_title,
            msg.message_id,
            link,
            ca,
            d,
        )

        if initial <= 0:
            return

        multiplier = d["mc"] / initial

        print(
            "CALL:",
            username,
            d["symbol"],
            multiplier,
        )

        # New calls can optionally be posted immediately.
        await context.bot.send_message(
            chat_id=TRACKER_CHANNEL,
            text=(
                f"⚡ <b>NEW KOL CALL</b>\n\n"
                f"📡 Source: {username}\n"
                f"🪙 {d['name']} - ${d['symbol']}\n\n"
                f"💰 MC: {money(d['mc'])}\n"
                f"💧 Liq: {money(d['liquidity'])}\n"
                f"📈 24h: {d['change']:.2f}%\n"
                f"📦 Vol: {money(d['volume'])}"
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    except Exception as e:
        print("POST ERROR:", repr(e))


# =========================================================
# LIVE MONITOR
# =========================================================

async def monitor(context: ContextTypes.DEFAULT_TYPE):
    if not TRACKER_CHANNEL:
        return

    c = db()

    rows = c.execute(
        """
        SELECT *
        FROM calls
        ORDER BY last_update DESC
        LIMIT 200
        """
    ).fetchall()

    c.close()

    for row in rows:
        try:
            d = get_dex(row["ca"])

            if not d or d["mc"] <= 0:
                continue

            refresh_call(
                row["id"],
                d,
            )

            initial = float(row["initial_mc"] or 0)

            if initial <= 0:
                continue

            multiplier = d["mc"] / initial

            # Check every milestone.
            for milestone in MILESTONES:

                if multiplier < milestone:
                    continue

                if not mark_milestone(
                    row["id"],
                    milestone,
                ):
                    continue

                fresh = get_call(row["id"])

                if not fresh:
                    continue

                text, keyboard = alert_text(
                    fresh,
                    d,
                    multiplier,
                    milestone,
                )

                await context.bot.send_message(
                    chat_id=TRACKER_CHANNEL,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=keyboard,
                )

                print(
                    "MILESTONE:",
                    row["symbol"],
                    milestone,
                    "x",
                )

        except Exception as e:
            print(
                "MONITOR ERROR:",
                row["ca"],
                repr(e),
            )


# =========================================================
# STARTUP
# =========================================================

async def post_init(app: Application):
    init_db()

    if app.job_queue:
        app.job_queue.run_repeating(
            monitor,
            interval=CHECK_SECONDS,
            first=15,
            name="alpha-monitor",
        )

    print("⚡ AlphaScope Tracker started")


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN secret is missing"
        )

    if not TRACKER_CHANNEL:
        raise RuntimeError(
            "TRACKER_CHANNEL secret is missing"
        )

    if not ADMIN_ID:
        raise RuntimeError(
            "ADMIN_ID secret is missing"
        )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("help", help_cmd)
    )

    app.add_handler(
        CommandHandler("track", track_cmd)
    )

    app.add_handler(
        CommandHandler("untrack", untrack_cmd)
    )

    app.add_handler(
        CommandHandler("channels", channels_cmd)
    )

    app.add_handler(
        CommandHandler("requests", requests_cmd)
    )

    app.add_handler(
        CallbackQueryHandler(callback)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_input,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.ChatType.CHANNEL,
            channel_post,
        )
    )

    print("⚡ AlphaScope ready")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
