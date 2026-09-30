import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ Welcome to AlphaScope!\n\n"
        "KOL tracking system is online."
    )


def main():
    token = os.getenv("BOT_TOKEN")

    if not token:
        raise ValueError("BOT_TOKEN is not configured")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))

    print("AlphaScope Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
