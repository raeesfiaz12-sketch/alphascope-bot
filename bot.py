import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)


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
    await update.message.reply_text(
        "⚡ Welcome to AlphaScope!\n\n"
        "Telegram KOL Call Tracking System\n\n"
        "Choose an option below:",
        reply_markup=main_menu(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "live_calls":
        text = (
            "🔥 Live Calls\n\n"
            "No calls are being tracked yet."
        )

    elif query.data == "track_channel":
        text = (
            "📡 Track My Channel\n\n"
            "Channel tracking setup will be available soon."
        )

    elif query.data == "leaderboard":
        text = (
            "📊 KOL Leaderboard\n\n"
            "Leaderboard data will appear here."
        )

    elif query.data == "search_kol":
        text = (
            "🔎 Search KOL\n\n"
            "KOL search will be available soon."
        )

    elif query.data == "performance":
        text = (
            "📈 Call Performance\n\n"
            "Call performance data will appear here."
        )

    elif query.data == "top_kols":
        text = (
            "🏆 Top KOLs\n\n"
            "Top performing KOLs will appear here."
        )

    elif query.data == "about":
        text = (
            "ℹ️ About AlphaScope\n\n"
            "AlphaScope tracks Telegram KOL calls "
            "and measures their performance using "
            "X, ATH X, ROI and other statistics."
        )

    elif query.data == "support":
        text = (
            "🆘 Support\n\n"
            "Contact: @AlphaScopeowner"
        )

    else:
        text = "Unknown option."

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
        ),
    )


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "⚡ AlphaScope\n\n"
        "Choose an option below:",
        reply_markup=main_menu(),
    )


def main():
    token = os.getenv("BOT_TOKEN")

    if not token:
        raise ValueError("BOT_TOKEN is not configured")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")
    )
    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    print("AlphaScope Bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main()
