import threading
import traceback

from django.core.management import BaseCommand

from parser.bot_instance import bot
from parser.management.commands.parser_emails import get_emails,export_mails_to_google_forms

is_running = False  # Флаг состояния бота
user_data = {}  # Хранилище данных пользователей

@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я бот для парсинга Gmail.\n\nИспользуйте /parse_emails для запуска.")


@bot.message_handler(commands=["parse_emails"])
def request_email(message):
    """Шаг 1: Запрашиваем email у пользователя"""
    global is_running

    if is_running:
        bot.reply_to(message, "⚠️ Бот уже выполняет парсинг. Подождите завершения.")
        return

    bot.send_message(message.chat.id, "📧 Введите вашу почту Gmail:")
    bot.register_next_step_handler(message, request_password)

def request_password(message):
    """Шаг 2: Запрашиваем пароль у пользователя"""
    user_data[message.chat.id] = {"email": message.text}
    bot.send_message(message.chat.id, "🔑 Введите пароль приложения (Google App Password):")
    bot.register_next_step_handler(message, start_parsing)

def start_parsing(message):
    """Шаг 3: Передаем email и пароль в get_emails()"""
    global is_running
    chat_id = message.chat.id

    if is_running:
        bot.reply_to(message, "⚠️ Бот уже выполняет парсинг. Подождите завершения.")
        return

    is_running = True  # Устанавливаем флаг "бот занят"

    user_data[chat_id]["password"] = message.text
    email = user_data[chat_id]["email"]
    password = user_data[chat_id]["password"]

    bot.send_message(chat_id, "⏳ Начинаю парсинг...")

    thread = threading.Thread(target=run_parsing, args=(chat_id, email, password))
    thread.start()

def run_parsing(chat_id, email, password):
    """Функция для запуска парсинга в отдельном потоке"""
    global is_running

    try:
        get_emails(email, password, chat_id)  # Теперь передаем `chat_id`
        bot.send_message(chat_id, "✅ Данные успешно записаны в таблицу.")
    except Exception as e:
        bot.send_message(chat_id, f"⚠ Ошибка: {str(e)}")
        traceback.print_exc()
    finally:
        is_running = False  # Сбрасываем флаг после завершения
        user_data.pop(chat_id, None)  # Удаляем данные пользователя

class Command(BaseCommand):
    def handle(self, *args, **options):
        bot.polling(none_stop=True)