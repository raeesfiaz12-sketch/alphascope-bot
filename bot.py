import os
import re
import json
import time
from urllib.request import Request, urlopen

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


# ============================================================
# CONFIGURATION
# ============================================================

TRACKER_CHANNEL = "@AlphaScopeTracker"

# Filter settings
MIN_MARKET_CAP = 10_000
MIN_LIQUIDITY = 5_000
MIN_VOLUME_24H = 10_000
MAX_AGE_HOURS = 24

# Admin user IDs
ADMIN_USER_IDS = {7494084812}


# ============================================================
# TEMPORARY STORAGE
# ============================================================

tracked_channels = {}

# Recently processed calls
live_calls = []

# Prevent duplicate contract addresses
SEEN_CAS = set()


# ============================================================
# MAIN MENU
# ============================================================

def main_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "🔥 Live Calls",
                callback_data="live_calls"
            ),

            InlineKeyboardButton(
                "📡 Track My Channel",
                callback_data="track_channel"
            ),
        ],

        [
            InlineKeyboardButton(
                "📊 KOL Leaderboard",
                callback_data="leaderboard"
            ),

            InlineKeyboardButton(
                "🔎 Search KOL",
                callback_data="search_kol"
            ),
        ],

        [
            InlineKeyboardButton(
                "📈 Call Performance",
                callback_data="performance"
            ),

            InlineKeyboardButton(
                "🏆 Top KOLs",
                callback_data="top_kols"
            ),
        ],

        [
            InlineKeyboardButton(
                "ℹ️ About AlphaScope",
                callback_data="about"
            ),

            InlineKeyboardButton(
                "🆘 Support",
                callback_data="support"
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# START COMMAND
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data["waiting_for_channel"] = False

    await update.message.reply_text(

        "⚡ Welcome to AlphaScope!\n\n"

        "Telegram KOL Call Tracking System\n\n"

        "Choose an option below:",

        reply_markup=main_menu()
    )


# ============================================================
# HELP COMMAND
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "🆘 Help\n\n"

        "Use /start to open the main menu.\n\n"

        "You can track Telegram channels and "
        "automatically process Solana KOL calls."
    )


# ============================================================
# BUTTON HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    # --------------------------------------------------------
    # LIVE CALLS
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # TRACK CHANNEL
    # --------------------------------------------------------

    elif query.data == "track_channel":

        context.user_data["waiting_for_channel"] = True

        text = (

            "📡 Track My Channel\n\n"

            "Send me your Telegram channel username.\n\n"

            "Example:\n"
            "@yourchannel\n\n"

            "⚠️ Make sure AlphaScope Bot is an "
            "admin of that channel."
        )


    # --------------------------------------------------------
    # LEADERBOARD
    # --------------------------------------------------------

    elif query.data == "leaderboard":

        text = (

            "📊 KOL Leaderboard\n\n"

            "Leaderboard data will appear here "
            "after calls are tracked."
        )


    # --------------------------------------------------------
    # SEARCH KOL
    # --------------------------------------------------------

    elif query.data == "search_kol":

        text = (

            "🔎 Search KOL\n\n"

            "KOL search will be available soon."
        )


    # --------------------------------------------------------
    # PERFORMANCE
    # --------------------------------------------------------

    elif query.data == "performance":

        text = (

            "📈 Call Performance\n\n"

            "Performance data will appear here "
            "after calls are tracked."
        )


    # --------------------------------------------------------
    # TOP KOLS
    # --------------------------------------------------------

    elif query.data == "top_kols":

        text = (

            "🏆 Top KOLs\n\n"

            "Top KOL statistics will appear here "
            "after calls are tracked."
        )


    # --------------------------------------------------------
    # ABOUT
    # --------------------------------------------------------

    elif query.data == "about":

        text = (

            "ℹ️ About AlphaScope\n\n"

            "AlphaScope tracks Telegram KOL calls "
            "and measures their performance using "
            "call and market data."
        )


    # --------------------------------------------------------
    # SUPPORT
    # --------------------------------------------------------

    elif query.data == "support":

        text = (

            "🆘 Support\n\n"

            "Contact: @AlphaScopeOwner"
        )


    else:

        text = "Unknown option."


    # --------------------------------------------------------
    # BACK TO MAIN MENU
    # --------------------------------------------------------

    await query.edit_message_text(

        text=text,

        reply_markup=InlineKeyboardMarkup(
            [[
                InlineKeyboardButton(
                    "🏠 Main Menu",
                    callback_data="main_menu"
                )
            ]]
        )
    )


# ============================================================
# MAIN MENU CALLBACK
# ============================================================

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

        reply_markup=main_menu()
    )


# ============================================================
# CHANNEL INPUT
# ============================================================

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

    # --------------------------------------------------------
    # Validate username
    # --------------------------------------------------------

    if not channel.startswith("@"):

        await update.message.reply_text(

            "❌ Invalid channel username.\n\n"

            "Please send it like:\n"
            "@yourchannel"
        )

        return

    user_id = update.effective_user.id

    # --------------------------------------------------------
    # Save tracked channel
    # --------------------------------------------------------

    tracked_channels[user_id] = channel

    context.user_data["waiting_for_channel"] = False

    await update.message.reply_text(

        "✅ Channel added for tracking!\n\n"

        f"📡 Channel: {channel}\n\n"

        "⚠️ Make sure AlphaScope Bot is an "
        "admin of that channel.\n\n"

        "New channel posts can then be processed "
        "by AlphaScope.",

        reply_markup=main_menu()
    )


# ============================================================
# CHANNEL POST
# ============================================================

async def channel_post(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.channel_post:
        return

    chat = update.channel_post.chat

    print(
        "🔥 CHANNEL POST RECEIVED:",
        chat.username
    )

    # --------------------------------------------------------
    # Channel username required
    # --------------------------------------------------------

    if not chat.username:

        print("⚠️ Channel has no public username")

        return

    channel_username = "@" + chat.username

    # --------------------------------------------------------
    # Check tracked channel
    # --------------------------------------------------------

    matching_users = [

        user_id

        for user_id, channel
        in tracked_channels.items()

        if channel.lower() == channel_username.lower()
    ]

    if not matching_users:

        print(
            "⏭️ Channel is not being tracked:",
            channel_username
        )

        return

    # --------------------------------------------------------
    # Get post text
    # --------------------------------------------------------

    message_text = (

        update.channel_post.text

        or update.channel_post.caption

        or ""

    ).strip()

    if not message_text:

        print("⚠️ Channel post has no text")

        return


    # ========================================================
    # 1. FIND SOLANA CONTRACT ADDRESS
    # ========================================================

    ca = None

    # Direct Solana contract address

    ca_match = re.search(

        r'(?<![A-Za-z0-9])'
        r'[1-9A-HJ-NP-Za-km-z]{32,44}'
        r'(?![A-Za-z0-9])',

        message_text
    )

    if ca_match:

        ca = ca_match.group(0)


    # --------------------------------------------------------
    # DexScreener URL
    # --------------------------------------------------------

    if not ca:

        dex_match = re.search(

            r'https?://'
            r'(?:www\.)?dexscreener\.com/'
            r'solana/'
            r'([1-9A-HJ-NP-Za-km-z]{32,44})',

            message_text,

            re.IGNORECASE
        )

        if dex_match:

            ca = dex_match.group(1)


    # --------------------------------------------------------
    # No CA
    # --------------------------------------------------------

    if not ca:

        print(
            "⚠️ No Solana CA found in channel post"
        )

        return


    print("🪙 CA DETECTED:", ca)


    # ========================================================
    # 2. DUPLICATE PROTECTION
    # ========================================================

    if ca in SEEN_CAS:

        print(
            "⏭️ Duplicate CA ignored:",
            ca
        )

        return


    # ========================================================
    # 3. GET DEXSCREENER DATA
    # ========================================================

    try:

        api_url = (
            "https://api.dexscreener.com/"
            f"token-pairs/v1/solana/{ca}"
        )

        req = Request(

            api_url,

            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json"
            }
        )


        with urlopen(
            req,
            timeout=15
        ) as response:

            data = json.loads(
                response.read().decode()
            )


        if not data:

            print(
                "⚠️ DexScreener returned no data"
            )

            return


        # ----------------------------------------------------
        # Get pairs
        # ----------------------------------------------------

        pairs = (

            data

            if isinstance(data, list)

            else []
        )


        if not pairs:

            print(
                "⚠️ No trading pairs found"
            )

            return


        # ----------------------------------------------------
        # Pick highest liquidity pair
        # ----------------------------------------------------

        pair = max(

            pairs,

            key=lambda x: float(

                (x.get("liquidity") or {})
                .get("usd")
                or 0
            )
        )


        # ====================================================
        # TOKEN INFORMATION
        # ====================================================

        base_token = (
            pair.get("baseToken")
            or {}
        )


        token_name = (
            base_token.get("name")
            or "Unknown"
        )


        token_symbol = (
            base_token.get("symbol")
            or "Unknown"
        )


        # ====================================================
        # MARKET DATA
        # ====================================================

        liquidity = float(

            (pair.get("liquidity") or {})
            .get("usd")
            or 0
        )


        market_cap = float(

            pair.get("marketCap")

            or pair.get("fdv")

            or 0
        )


        volume_24h = float(

            (pair.get("volume") or {})
            .get("h24")
            or 0
        )


        price_change_24h = float(

            (pair.get("priceChange") or {})
            .get("h24")
            or 0
        )


        pair_created = pair.get(
            "pairCreatedAt"
        )


        # ====================================================
        # TOKEN AGE
        # ====================================================

        age_text = "Unknown"
        age_seconds = None


        if pair_created:

            age_seconds = max(

                0,

                int(time.time() * 1000)
                - int(pair_created)
            )


            minutes = (
                age_seconds // 60000
            )


            hours = (
                minutes // 60
            )


            days = (
                hours // 24
            )


            if days > 0:

                age_text = f"{days}d"

            elif hours > 0:

                age_text = f"{hours}h"

            else:

                age_text = f"{minutes}m"


        # ====================================================
        # FILTER 1 — MARKET CAP
        # ====================================================

        if market_cap < MIN_MARKET_CAP:

            print(

                f"⏭️ Rejected: MC "
                f"${market_cap:,.2f} "
                f"< ${MIN_MARKET_CAP:,.2f}"
            )

            return


        # ====================================================
        # FILTER 2 — LIQUIDITY
        # ====================================================

        if liquidity < MIN_LIQUIDITY:

            print(

                f"⏭️ Rejected: Liquidity "
                f"${liquidity:,.2f} "
                f"< ${MIN_LIQUIDITY:,.2f}"
            )

            return


        # ====================================================
        # FILTER 3 — VOLUME
        # ====================================================

        if volume_24h < MIN_VOLUME_24H:

            print(

                f"⏭️ Rejected: Volume "
                f"${volume_24h:,.2f} "
                f"< ${MIN_VOLUME_24H:,.2f}"
            )

            return


        # ====================================================
        # FILTER 4 — AGE
        # ====================================================

        if age_seconds is None:

            print(
                "⏭️ Rejected: Token age unavailable"
            )

            return


        max_age_ms = (
            MAX_AGE_HOURS
            * 60
            * 60
            * 1000
        )


        if age_seconds > max_age_ms:

            print(

                f"⏭️ Rejected: Token older "
                f"than {MAX_AGE_HOURS} hours"
            )

            return


        # ====================================================
        # LINKS
        # ====================================================

        chart_url = (
            f"https://dexscreener.com/solana/{ca}"
        )


        twitter_url = None


        info = pair.get("info") or {}

        socials = (
            info.get("socials") or []
        )


        for social in socials:

            if social.get("type") == "twitter":

                twitter_url = social.get("url")

                break


        # ====================================================
        # SAVE LIVE CALL
        # ====================================================

        call_text = (

            f"{channel_username}\n"
            f"{token_name} (${token_symbol})\n"
            f"{ca}"
        )


        live_calls.append(call_text)


        # Keep last 50 calls

        if len(live_calls) > 50:

            del live_calls[:-50]


        # ====================================================
        # CREATE BUTTONS
        # ====================================================

        buttons = [

            [
                InlineKeyboardButton(
                    "📊 Chart",
                    url=chart_url
                )
            ]
        ]


        if twitter_url:

            buttons[0].append(

                InlineKeyboardButton(
                    "🐦 Twitter",
                    url=twitter_url
                )
            )


        reply_markup = (
            InlineKeyboardMarkup(buttons)
        )


        # ====================================================
        # CREATE ALPHASCOPE POST
        # ====================================================

        text = (

            "⚡ <b>NEW KOL CALL</b>\n"

            "━━━━━━━━━━━━━━\n\n"

            f"📡 <b>Source:</b> "
            f"{channel_username}\n\n"

            f"🪙 <b>{token_name}</b> "
            f"- ${token_symbol}\n\n"

            f"<b>Solana CA:</b>\n"

            f"<code>{ca}</code>\n\n"

            f"🌱 Age: {age_text} | "

            f"💰 MC: "
            f"${market_cap:,.2f} | "

            f"💧 Liq: "
            f"${liquidity:,.2f}\n"

            f"📈 24h: "
            f"{price_change_24h:.2f}% | "

            f"Vol: "
            f"${volume_24h:,.2f}\n\n"

            "━━━━━━━━━━━━━━\n"

            "⚡ <b>AlphaScope Tracker</b>"
        )


        # ====================================================
        # SEND TO TRACKER CHANNEL
        # ====================================================

        for user_id in matching_users:

            try:

                await context.bot.send_message(

                    chat_id=TRACKER_CHANNEL,

                    text=text,

                    parse_mode="HTML",

                    disable_web_page_preview=True,

                    reply_markup=reply_markup
                )


                print(
                    "✅ AlphaScope post sent"
                )


                # Mark CA as processed
                SEEN_CAS.add(ca)


                print(
                    "✅ CA marked as processed:",
                    ca
                )


            except Exception as e:

                print(
                    "❌ Could not post "
                    f"to tracker channel: {e}"
                )


    # ========================================================
    # GENERAL ERROR
    # ========================================================

    except Exception as e:

        print(
            "❌ Error processing "
            f"channel post: {e}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    token = os.getenv("BOT_TOKEN")


    if not token:

        raise ValueError(
            "BOT_TOKEN is not configured"
        )


    # --------------------------------------------------------
    # CREATE APPLICATION
    # --------------------------------------------------------

    app = (

        Application.builder()

        .token(token)

        .build()
    )


    # --------------------------------------------------------
    # COMMANDS
    # --------------------------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )


    # --------------------------------------------------------
    # MAIN MENU CALLBACK
    # --------------------------------------------------------

    app.add_handler(

        CallbackQueryHandler(

            main_menu_callback,

            pattern="^main_menu$"
        )
    )


    # --------------------------------------------------------
    # OTHER BUTTONS
    # --------------------------------------------------------

    app.add_handler(

        CallbackQueryHandler(
            button_handler
        )
    )


    # --------------------------------------------------------
    # CHANNEL INPUT
    # --------------------------------------------------------

    app.add_handler(

        MessageHandler(

            filters.TEXT
            & ~filters.COMMAND,

            channel_input
        )
    )


    # --------------------------------------------------------
    # CHANNEL POSTS
    # --------------------------------------------------------

    app.add_handler(

        MessageHandler(

            filters.UpdateType.CHANNEL_POST,

            channel_post
        )
    )


    print(
        "⚡ AlphaScope Bot is running..."
    )


    # --------------------------------------------------------
    # START POLLING
    # --------------------------------------------------------

    app.run_polling(

        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
