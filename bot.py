import os
import sqlite3
import logging
from datetime import datetime

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
)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

OWNER_ID = int(os.getenv("OWNER_ID", "0"))

DB_FILE = "alphascope.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("AlphaScope")


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            title TEXT,
            invite_link TEXT,
            active INTEGER DEFAULT 1,
            added_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            channel_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            UNIQUE(user_id, channel_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tracked (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            added_by INTEGER,
            added_at TEXT
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# HELPERS
# ============================================================

def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID


def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


async def send_admin_request(
    context: ContextTypes.DEFAULT_TYPE,
    request_id: int,
    user,
    channel
):
    text = (
        "🔔 <b>New Channel Request</b>\n\n"
        f"👤 User: <code>{user.id}</code>\n"
        f"Username: @{user.username or 'No username'}\n"
        f"📢 Channel: <b>{channel['title'] or channel['username']}</b>\n"
        f"🔗 @{channel['username']}\n\n"
        "Choose an action:"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Accept",
                callback_data=f"accept:{request_id}"
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"reject:{request_id}"
            ),
        ]
    ]

    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    text = (
        "🚀 <b>AlphaScope Bot</b>\n\n"
        "Welcome!\n\n"
        "📢 /channels - View available channels\n"
        "📊 /active - Active tracked channels\n"
        "📈 /stats - Bot statistics\n"
        "❓ /help - Help\n"
    )

    if is_admin(user.id):
        text += (
            "\n👑 <b>Admin Commands</b>\n"
            "/requests - Pending requests\n"
            "/track - Track a channel\n"
            "/untrack - Stop tracking\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# ============================================================
# HELP
# ============================================================

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = (
        "📚 <b>AlphaScope Help</b>\n\n"
        "/start - Start bot\n"
        "/channels - Channel list\n"
        "/active - Active channels\n"
        "/stats - Statistics\n"
        "/help - Help\n\n"
        "Channel list mein kisi channel ko select karke "
        "access request bhej sakte ho."
    )

    if is_admin(update.effective_user.id):
        text += (
            "\n\n👑 <b>Admin</b>\n"
            "/requests - Pending requests\n"
            "/track @channel - Add channel\n"
            "/untrack @channel - Remove channel"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# ============================================================
# CHANNEL LIST
# ============================================================

async def channels_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):

    conn = db()
    channels = conn.execute("""
        SELECT * FROM channels
        WHERE active = 1
        ORDER BY id DESC
    """).fetchall()
    conn.close()

    if not channels:
        await update.message.reply_text(
            "📭 Abhi koi channel list mein nahi hai."
        )
        return

    keyboard = []

    for ch in channels:

        title = ch["title"] or f"@{ch['username']}"

        keyboard.append([
            InlineKeyboardButton(
                f"📢 {title}",
                callback_data=f"channel:{ch['id']}"
            )
        ])

    await update.message.reply_text(
        "📋 <b>Available Channels</b>\n\n"
        "Kisi channel par click karo:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ============================================================
# CHANNEL CLICK
# ============================================================

async def channel_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query
    await query.answer()

    channel_id = int(query.data.split(":")[1])

    conn = db()
    channel = conn.execute(
        "SELECT * FROM channels WHERE id = ?",
        (channel_id,)
    ).fetchone()

    if not channel:
        conn.close()

        await query.edit_message_text(
            "❌ Channel nahi mila."
        )
        return

    user_id = query.from_user.id
    username = query.from_user.username or ""

    existing = conn.execute("""
        SELECT * FROM requests
        WHERE user_id = ?
        AND channel_id = ?
    """, (user_id, channel_id)).fetchone()

    if existing and existing["status"] == "pending":

        conn.close()

        await query.edit_message_text(
            "⏳ Tumhari request already pending hai."
        )
        return

    # Existing old request ko dobara allow karne ke liye
    conn.execute("""
        DELETE FROM requests
        WHERE user_id = ?
        AND channel_id = ?
    """, (user_id, channel_id))

    cur = conn.execute("""
        INSERT INTO requests
        (user_id, username, channel_id, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
    """, (
        user_id,
        username,
        channel_id,
        now()
    ))

    request_id = cur.lastrowid

    conn.commit()
    conn.close()

    await query.edit_message_text(
        "📨 <b>Request Sent!</b>\n\n"
        f"📢 Channel: @{channel['username']}\n\n"
        "Admin ko request bhej di gayi hai.\n"
        "Approval ke baad access milega.",
        parse_mode="HTML"
    )

    await send_admin_request(
        context,
        request_id,
        query.from_user,
        channel
    )


# ============================================================
# ADMIN ACCEPT / REJECT
# ============================================================

async def request_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer(
            "❌ Sirf admin ye action kar sakta hai.",
            show_alert=True
        )
        return

    await query.answer()

    action, request_id = query.data.split(":")
    request_id = int(request_id)

    conn = db()

    request = conn.execute("""
        SELECT
            requests.*,
            channels.username AS channel_username,
            channels.title AS channel_title
        FROM requests
        JOIN channels
        ON requests.channel_id = channels.id
        WHERE requests.id = ?
    """, (request_id,)).fetchone()

    if not request:
        conn.close()

        await query.edit_message_text(
            "❌ Request nahi mili."
        )
        return

    if request["status"] != "pending":
        conn.close()

        await query.edit_message_text(
            "ℹ️ Ye request already process ho chuki hai."
        )
        return

    if action == "accept":

        conn.execute("""
            UPDATE requests
            SET status = 'accepted'
            WHERE id = ?
        """, (request_id,))

        conn.commit()
        conn.close()

        await query.edit_message_text(
            "✅ <b>Request Accepted</b>\n\n"
            f"📢 @{request['channel_username']}\n"
            f"👤 User ID: <code>{request['user_id']}</code>",
            parse_mode="HTML"
        )

        try:
            await context.bot.send_message(
                chat_id=request["user_id"],
                text=(
                    "✅ <b>Your request has been accepted!</b>\n\n"
                    f"📢 @{request['channel_username']}\n\n"
                    "You now have access."
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(
                "Could not notify user: %s",
                e
            )

    elif action == "reject":

        conn.execute("""
            UPDATE requests
            SET status = 'rejected'
            WHERE id = ?
        """, (request_id,))

        conn.commit()
        conn.close()

        await query.edit_message_text(
            "❌ <b>Request Rejected</b>\n\n"
            f"📢 @{request['channel_username']}\n"
            f"👤 User ID: <code>{request['user_id']}</code>",
            parse_mode="HTML"
        )

        try:
            await context.bot.send_message(
                chat_id=request["user_id"],
                text=(
                    "❌ <b>Your channel request was rejected.</b>\n\n"
                    f"📢 @{request['channel_username']}"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(
                "Could not notify user: %s",
                e
            )


# ============================================================
# ADMIN REQUESTS
# ============================================================

async def requests_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ Admin only."
        )
        return

    conn = db()

    requests = conn.execute("""
        SELECT
            requests.*,
            channels.username AS channel_username,
            channels.title AS channel_title
        FROM requests
        JOIN channels
        ON requests.channel_id = channels.id
        WHERE requests.status = 'pending'
        ORDER BY requests.id DESC
    """).fetchall()

    conn.close()

    if not requests:
        await update.message.reply_text(
            "📭 Koi pending request nahi hai."
        )
        return

    for req in requests:

        keyboard = [[
            InlineKeyboardButton(
                "✅ Accept",
                callback_data=f"accept:{req['id']}"
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"reject:{req['id']}"
            ),
        ]]

        await update.message.reply_text(
            "🔔 <b>Pending Request</b>\n\n"
            f"👤 User ID: <code>{req['user_id']}</code>\n"
            f"👤 Username: @{req['username'] or 'None'}\n"
            f"📢 Channel: @{req['channel_username']}\n"
            f"🕒 {req['created_at']}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# ============================================================
# TRACK CHANNEL
# ============================================================

async def track_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ Admin only."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Usage:\n/track @channel"
        )
        return

    username = context.args[0].strip()

    if username.startswith("https://t.me/"):
        username = username.replace(
            "https://t.me/",
            ""
        )

    username = username.lstrip("@").strip()

    conn = db()

    try:
        conn.execute("""
            INSERT INTO channels
            (username, title, invite_link, active, added_at)
            VALUES (?, ?, ?, 1, ?)
        """, (
            username,
            f"@{username}",
            f"https://t.me/{username}",
            now()
        ))

        conn.commit()

    except sqlite3.IntegrityError:

        conn.execute("""
            UPDATE channels
            SET active = 1
            WHERE username = ?
        """, (username,))

        conn.commit()

    conn.close()

    await update.message.reply_text(
        f"✅ Channel added:\n\n"
        f"📢 @{username}\n"
        f"🔗 https://t.me/{username}"
    )


# ============================================================
# UNTRACK
# ============================================================

async def untrack_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ Admin only."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Usage:\n/untrack @channel"
        )
        return

    username = context.args[0].strip()
    username = username.lstrip("@")

    conn = db()

    conn.execute("""
        UPDATE channels
        SET active = 0
        WHERE username = ?
    """, (username,))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🛑 @{username} tracking/list se remove kar diya."
    )


# ============================================================
# ACTIVE
# ============================================================

async def active_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    conn = db()

    channels = conn.execute("""
        SELECT * FROM channels
        WHERE active = 1
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    if not channels:
        await update.message.reply_text(
            "📭 Koi active channel nahi."
        )
        return

    text = "🟢 <b>Active Channels</b>\n\n"

    for i, channel in enumerate(channels, 1):
        text += (
            f"{i}. @{channel['username']}\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# ============================================================
# STATS
# ============================================================

async def stats_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    conn = db()

    channels = conn.execute(
        "SELECT COUNT(*) AS c FROM channels WHERE active = 1"
    ).fetchone()["c"]

    total_requests = conn.execute(
        "SELECT COUNT(*) AS c FROM requests"
    ).fetchone()["c"]

    pending = conn.execute("""
        SELECT COUNT(*) AS c
        FROM requests
        WHERE status = 'pending'
    """).fetchone()["c"]

    accepted = conn.execute("""
        SELECT COUNT(*) AS c
        FROM requests
        WHERE status = 'accepted'
    """).fetchone()["c"]

    rejected = conn.execute("""
        SELECT COUNT(*) AS c
        FROM requests
        WHERE status = 'rejected'
    """).fetchone()["c"]

    conn.close()

    text = (
        "📊 <b>AlphaScope Statistics</b>\n\n"
        f"📢 Active Channels: <b>{channels}</b>\n"
        f"📨 Total Requests: <b>{total_requests}</b>\n"
        f"⏳ Pending: <b>{pending}</b>\n"
        f"✅ Accepted: <b>{accepted}</b>\n"
        f"❌ Rejected: <b>{rejected}</b>"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Exception while handling update:",
        exc_info=context.error
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN secret is missing"
        )

    if not OWNER_ID:
        raise RuntimeError(
            "OWNER_ID secret is missing"
        )

    init_db()

    print("🚀 AlphaScope Bot starting...")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # User commands
    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("help", help_cmd)
    )

    app.add_handler(
        CommandHandler("channels", channels_cmd)
    )

    app.add_handler(
        CommandHandler("active", active_cmd)
    )

    app.add_handler(
        CommandHandler("stats", stats_cmd)
    )

    # Admin commands
    app.add_handler(
        CommandHandler("requests", requests_cmd)
    )

    app.add_handler(
        CommandHandler("track", track_cmd)
    )

    app.add_handler(
        CommandHandler("untrack", untrack_cmd)
    )

    # Buttons
    app.add_handler(
        CallbackQueryHandler(
            channel_callback,
            pattern=r"^channel:"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            request_callback,
            pattern=r"^(accept|reject):"
        )
    )

    app.add_error_handler(error_handler)

    print("✅ AlphaScope Bot is running...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
