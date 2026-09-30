import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Temporary in-memory storage
tracked_channels = {}
live_calls = []


def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("🔥 Live Calls", callback_data="live_calls"),
            InlineKeyboardButton("📡 Track My Channel", callback_data="track_channel"),
        ],
        [
            InlineKeyboardButton("📊 KOL Leaderboard", callback_data="leaderboard"),
            InlineKeyboardButton("🔎 Search KOL", callback_data="search_kol"),
        ],
        [
            InlineKeyboardButton("📈 Call Performance", callback_data="performance"),
            InlineKeyboardButton("🏆 Top KOLs", callback_data="top_kols"),
        ],
        [
            InlineKeyboardButton("ℹ️ About AlphaScope", callback_data="about"),
            InlineKeyboardButton("🆘 Support", callback_data="support"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting_for_channel"] = False

    await update.message.reply_text(
        "⚡ Welcome to AlphaScope!\n\n"
        "Telegram KOL Call Tracking System\n\n"
        "Choose an option below:",
        reply_markup=main_menu(),
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 Help\n\n"
        "Use /start to open the main menu.\n"
        "You can track Telegram channels and view KOL data."
    )
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "live_calls":
        if not live_calls:
            text = (
                "🔥 Live Calls\n\n"
                "No calls are being tracked yet."
            )
        else:
            text = "🔥 Live Calls\n\n"
            for call in live_calls[-10:]:
                text += f"• {call}\n"

    elif query.data == "track_channel":
        context.user_data["waiting_for_channel"] = True

        text = (
            "📡 Track My Channel\n\n"
            "Send me your Telegram channel username.\n\n"
            "Example:\n"
            "@yourchannel\n\n"
            "⚠️ Make sure AlphaTrackerBot is an admin "
            "of that channel."
        )

    elif query.data == "leaderboard":
        text = (
            "📊 KOL Leaderboard\n\n"
            "Leaderboard data will appear here "
            "after calls are tracked."
        )

    elif query.data == "search_kol":
        text = (
            "🔎 Search KOL\n\n"
            "KOL search will be available soon."
        )

    elif query.data == "performance":
        text = (
            "📈 Call Performance\n\n"
            "Performance data will appear here "
            "after calls are tracked."
        )

    elif query.data == "top_kols":
        text = (
            "🏆 Top KOLs\n\n"
            "Top KOL statistics will appear here "
            "after calls are tracked."
        )

    elif query.data == "about":
        text = (
            "ℹ️ About AlphaScope\n\n"
            "AlphaScope tracks Telegram KOL calls "
            "and measures their performance using "
            "call and market data."
        )

    elif query.data == "support":
        text = (
            "🆘 Support\n\n"
            "Contact: @AlphaScopeOwner"
        )

    else:
        text = "Unknown option."

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(
            [[
                InlineKeyboardButton(
                    "🏠 Main Menu",
                    callback_data="main_menu"
                )
            ]]
        ),
    )


async def main_menu_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    context.user_data["waiting_for_channel"] = False

    await query.edit_message_text(
        "⚡ AlphaScope\n\n"
        "Choose an option below:",
        reply_markup=main_menu(),
    )


async def channel_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_data = context.user_data

    if user_data is None:
        return

    if not user_data.get("waiting_for_channel"):
        return

    channel = update.message.text.strip()

    if not channel.startswith("@"):
        await update.message.reply_text(
            "❌ Invalid channel username.\n\n"
            "Please send it like:\n"
            "@yourchannel"
        )
        return

    user_id = update.effective_user.id

    tracked_channels[user_id] = channel

    context.user_data["waiting_for_channel"] = False

    await update.message.reply_text(
        "✅ Channel added for tracking!\n\n"
        f"📡 Channel: {channel}\n\n"
        "⚠️ Make sure AlphaTrackerBot is an admin "
        "of this channel.\n\n"
        "New channel posts can then be processed "
        "by AlphaScope.",
        reply_markup=main_menu(),
    )


async def channel_post(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.channel_post:
        return

    print("🔥 CHANNEL POST RECEIVED:", update.channel_post.chat.username)

    chat = update.channel_post.chat

    if not chat.username:
        return

    channel_username = "@" + chat.username

    # Check if this channel is being tracked
    matching_users = [
        user_id
        for user_id, channel in tracked_channels.items()
        if channel.lower() == channel_username.lower()
    ]

    if not matching_users:
        return

    message_text = (
        update.channel_post.text
        or update.channel_post.caption
        or ""
    ).strip()

    if not message_text:
        return

    import re
    import json
    from urllib.request import Request, urlopen
    from urllib.parse import urlparse

    # --------------------------------------------------
    # 1. Find Solana CA or DexScreener URL
    # --------------------------------------------------

    ca = None

    # Direct Solana contract address
    ca_match = re.search(
        r'(?<![A-Za-z0-9])[1-9A-HJ-NP-Za-km-z]{32,44}(?![A-Za-z0-9])',
        message_text
    )

    if ca_match:
        ca = ca_match.group(0)

    # DexScreener URL
    if not ca:
        dex_match = re.search(
            r'https?://(?:www\.)?dexscreener\.com/solana/([1-9A-HJ-NP-Za-km-z]{32,44})',
            message_text,
            re.IGNORECASE
        )

        if dex_match:
            ca = dex_match.group(1)

    if not ca:
        print("⚠️ No Solana CA found in channel post")
        return

    print("🪙 CA DETECTED:", ca)

    # --------------------------------------------------
    # 2. Get token data from DexScreener
    # --------------------------------------------------

    try:
        api_url = f"https://api.dexscreener.com/token-pairs/v1/solana/{ca}"

        req = Request(
            api_url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json"
            }
        )

        with urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())

        if not data:
            print("⚠️ DexScreener returned no data")
            return

        # Pick pair with highest liquidity
        pairs = data if isinstance(data, list) else []

        if not pairs:
            return

        pair = max(
            pairs,
            key=lambda x: float(
                (x.get("liquidity") or {}).get("usd") or 0
            )
        )

        base_token = pair.get("baseToken") or {}

        token_name = base_token.get("name") or "Unknown"
        token_symbol = base_token.get("symbol") or "Unknown"

        # --------------------------------------------------
        # 3. Market data
        # --------------------------------------------------

        liquidity = float(
            (pair.get("liquidity") or {}).get("usd") or 0
        )

        market_cap = float(
            pair.get("marketCap")
            or pair.get("fdv")
            or 0
        )

        volume_24h = float(
            (pair.get("volume") or {}).get("h24") or 0
        )

        price_change_24h = float(
            (pair.get("priceChange") or {}).get("h24") or 0
        )

        pair_created = pair.get("pairCreatedAt")

        # --------------------------------------------------
        # 4. Token age
        # --------------------------------------------------

        age_text = "Unknown"

        if pair_created:
            import time

            age_seconds = max(
                0,
                int(time.time() * 1000) - int(pair_created)
            )

            minutes = age_seconds // 60000
            hours = minutes // 60
            days = hours // 24

            if days > 0:
                age_text = f"{days}d"
            elif hours > 0:
                age_text = f"{hours}h"
            else:
                age_text = f"{minutes}m"

        # --------------------------------------------------
        # 5. Links
        # --------------------------------------------------

        chart_url = (
            f"https://dexscreener.com/solana/{ca}"
        )

        twitter_url = None

        info = pair.get("info") or {}
        socials = info.get("socials") or []

        for social in socials:
            if social.get("type") == "twitter":
                twitter_url = social.get("url")
                break

        # --------------------------------------------------
        # 6. Save live call
        # --------------------------------------------------

        call_text = (
            f"{channel_username}\n"
            f"{token_name} (${token_symbol})\n"
            f"{ca}"
        )

        live_calls.append(call_text)

        if len(live_calls) > 50:
            del live_calls[:-50]

        # --------------------------------------------------
        # 7. Create AlphaScope post
        # --------------------------------------------------

        twitter_line = ""

        if twitter_url:
            twitter_line = (
                f'🔗 <a href="{twitter_url}">Twitter</a>'
            )
        else:
            twitter_line = "🔗 Twitter"

        text = (
            "⚡ <b>NEW KOL CALL</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"📡 <b>Source:</b> {channel_username}\n\n"
            f"🪙 <b>{token_name}</b> - ${token_symbol}\n\n"
            f"<b>Solana CA:</b>\n"
            f"<code>{ca}</code>\n\n"
            f"🌱 Age: {age_text} | "
            f"💰 MC: ${market_cap:,.2f} | "
            f"💧 Liq: ${liquidity:,.2f}\n"
            f"📈 24h: {price_change_24h:.2f}% | "
            f"Vol: ${volume_24h:,.2f}\n\n"
            f'📊 <a href="{chart_url}">Chart</a>\n'
            f"{twitter_line}\n\n"
            "━━━━━━━━━━━━━━\n"
            "⚡ <b>AlphaScope Tracker</b>"
        )

        # --------------------------------------------------
        # 8. Post to AlphaScope Tracker
        # --------------------------------------------------

        for user_id in matching_users:
            try:
                await context.bot.send_message(
                    chat_id="@AlphaScopeTracker",
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )

                print("✅ AlphaScope post sent")

            except Exception as e:
                print(f"❌ Could not post to tracker channel: {e}")

    except Exception as e:
        print(f"❌ Error processing channel post: {e}")

def main():
    token = os.getenv("BOT_TOKEN")

    if not token:
        raise ValueError(
            "BOT_TOKEN is not configured"
        )

    app = (
        Application.builder()
        .token(token)
        .build()
    )
    

    app.add_handler(
        CommandHandler("start", start)
    )
    app.add_handler(
        CommandHandler("help", help_command)
    )
    app.add_handler(
        CallbackQueryHandler(
            main_menu_callback,
            pattern="^main_menu$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            channel_input
        )
    )

    app.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST,
            channel_post
        )
    )

    print("AlphaScope Bot is running...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
