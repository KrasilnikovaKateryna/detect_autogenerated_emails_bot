import traceback

import telebot
from django.core.management import BaseCommand

from parser.management.commands.parser_emails import get_html_emails,export_news_to_google_forms

TOKEN = "8107264435:AAF_rwAoW5cLKJwYy-1Wsj3gQT5tL4BZYEY"
bot = telebot.TeleBot(TOKEN)

user_data = {}

@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я бот для парсинга Gmail.\n\nИспользуйте /parse_emails для запуска.")

@bot.message_handler(commands=["parse_emails"])
def request_email(message):
    """Шаг 1: Запрашиваем email у пользователя"""
    bot.send_message(message.chat.id, "📧 Введите вашу почту Gmail:")
    bot.register_next_step_handler(message, request_password)

def request_password(message):
    """Шаг 2: Запрашиваем пароль у пользователя"""
    user_data[message.chat.id] = {"email": message.text}
    bot.send_message(message.chat.id, "🔑 Введите пароль приложения (Google App Password):")
    bot.register_next_step_handler(message, start_parsing)

def start_parsing(message):
    """Шаг 3: Передаем email и пароль в get_html_emails()"""
    chat_id = message.chat.id
    user_data[chat_id]["password"] = message.text

    email = user_data[chat_id]["email"]
    password = user_data[chat_id]["password"]

    bot.send_message(chat_id, "⏳ Начинаю парсинг...")

    try:
        get_html_emails(email, password)  # Запуск скрипта парсинга почты
        bot.reply_to(message, "✅ Парсинг завершен! Данные сохранены в базе.")
        bot.reply_to(message, "✅ Сохранение в таблицу...")
        export_news_to_google_forms()
        bot.reply_to(message, "✅ Данные записаны в таблицу.")
    except Exception as e:
        # bot.reply_to(message, f"⚠ Ошибка: {str(e)}")
        traceback.print_exc()

    # Удаляем данные из памяти
    del user_data[chat_id]

class Command(BaseCommand):

    def handle(self, *args, **options):
        bot.polling(none_stop=True)