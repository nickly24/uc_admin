import os

import telebot
from telebot import types


BOT_TOKEN = "8331847785:AAEOrkhCGwwDPsDsodZpGOespnrNQZuJ6-8"
MINI_APP_URL = "https://nickly24-uc3-ad1c.twc1.net/"

SUPPORT_URL = "https://t.me/MISS_uc_manager"
WELCOME_TEXT = (
    "Добро пожаловать в бот пополнений MISS UC!\n"
    "Нажмите кнопку ниже, чтобы открыть мини-приложение, "
    "или обратитесь в поддержку."
)
FALLBACK_TEXT = "Пожалуйста, обратитесь в поддержку: https://t.me/MISS_uc_manager"


def _build_keyboard() -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton(
            text="Открыть приложение",
            web_app=types.WebAppInfo(url=MINI_APP_URL),
        ),
        types.InlineKeyboardButton(text="Поддержка", url=SUPPORT_URL),
    )
    return keyboard


def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_BOT_TOKEN_HERE":
        raise ValueError("Укажите токен бота в BOT_TOKEN в tgbot/bot.py")

    bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

    @bot.message_handler(commands=["start"])
    def handle_start(message: types.Message) -> None:
        keyboard = _build_keyboard()
        with open(os.path.join(os.path.dirname(__file__), "banner.jpg"), "rb") as photo:
            bot.send_photo(
                message.chat.id,
                photo=photo,
                caption=WELCOME_TEXT,
                reply_markup=keyboard,
            )

    @bot.message_handler(func=lambda msg: True, content_types=["text"])
    def handle_other_messages(message: types.Message) -> None:
        if message.text and message.text.strip().startswith("/start"):
            return
        bot.send_message(message.chat.id, FALLBACK_TEXT)

    bot.infinity_polling()


if __name__ == "__main__":
    main()
