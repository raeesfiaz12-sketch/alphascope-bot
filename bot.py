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

    chat = update.channel_post.chat

    if not chat.username:
        return

    channel_username = "@" + chat.username

    matching_users = [
        user_id
        for user_id, channel in tracked_channels.items()
        if channel.lower() == channel_username.lower()
    ]

    if not matching_users:
        return

    message_text = update.channel_post.text or update.channel_post.caption

    if not message_text:
        return

    call_text = (
        f"{channel_username}: "
        f"{message_text[:500]}"
    )

    live_calls.append(call_text)

    # Keep memory small
    if len(live_calls) > 50:
        del live_calls[:-50]

    for user_id in matching_users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🔥 New Channel Post\n\n"
                    f"📡 {channel_username}\n\n"
                    f"{message_text[:3500]}"
                ),
            )
        except Exception as e:
            print(f"Could not notify user {user_id}: {e}")


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
