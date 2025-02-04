import imaplib
import email
import re
import traceback
from datetime import datetime
from email.header import decode_header
import requests
import spacy
from openai import OpenAI

from parser.bot_instance import bot
from parser.models import AutoNews, UserNews
import openai

# Учетные данные
IMAP_SERVER = "imap.gmail.com"
nlp = spacy.load("en_core_web_sm")


def analyze_email_content(subject, sender, body, sent_at):
    print(f"Тема: {subject}")
    print(f"Отправитель: {sender}")
    print(f"Время отправки: {sent_at}")

    is_automated = False

    sender_name, sender_email = extract_sender_info(sender)

    if sender_email and "no-reply" in sender_email.lower():
        is_automated = True

    if "unsubscribe" in body.lower():
        is_automated = True

    automated_phrases = [
        "do not reply", "automated message", "click here",
        "manage your preferences", "update your settings"
    ]
    for phrase in automated_phrases:
        if phrase in body.lower():
            is_automated = True

    if re.search(r"<html>|<body>|<div>", body, re.IGNORECASE):
        is_automated = True


    name = extract_name_from_email(body)
    if name != 'Unknown':
        sender_name = name

    if is_automated:
        save_auto_news(sender_name, sender_email, body, sent_at)
        send_to_google_forms(sent_at, sender_name, sender_email, body, auto_gen=True)
    else:
        extracted_name = extract_name_from_email(body)
        if extracted_name is not None:
            sender_name = extracted_name
        print(f"🎯 Извлеченное имя: {extracted_name}")

        save_user_news(sender_name, sender_email, body, sent_at)
        send_to_google_forms(sent_at, sender_name, sender_email, body, auto_gen=False)

    print("=" * 50)


def extract_sender_info(sender):
    match = re.match(r'(?:"?([^"]*)"?\s)?(?:<?([\w\.-]+@[\w\.-]+)>?)', sender)
    if match:
        sender_name = match.group(1) if match.group(1) else match.group(2)
        sender_email = match.group(2)
        return sender_name, sender_email
    return sender, sender


def parse_email_date(date_str):
    try:
        return datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")  # Формат даты в заголовках email
    except Exception:
        return None


def save_auto_news(sender_name, sender_email, content, sent_at):
    news = AutoNews(sender_name=sender_name, sender_email=sender_email, content=content, sent_at=sent_at)
    news.save()
    print("✅ Автоматическая новость сохранена в AutoNews")


def save_user_news(sender_name, sender_email, content, sent_at):
    news = UserNews(sender_name=sender_name, sender_email=sender_email, content=content, sent_at=sent_at)
    news.save()
    print("✅ Новость от реального человека сохранена в UserNews")


# Получение данных письма
def fetch_email_data(mail, email_id):
    status, msg_data = mail.fetch(email_id, "(RFC822)")
    return msg_data

# Парсинг письма
def parse_email(msg):
    try:
        subject, encoding = decode_header(msg["Subject"])[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding if encoding else "utf-8")

        sender = msg.get("From")
        date_str = msg["Date"]

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        body = part.get_payload(decode=True).decode()
                    except:
                        traceback.print_exc()
                    break
                elif content_type == "text/html":
                    try:
                        body = part.get_payload(decode=True).decode()
                    except:
                        traceback.print_exc()
                    break
        else:
            content_type = msg.get_content_type()
            if content_type in ["text/plain", "text/html"]:
                body = msg.get_payload(decode=True).decode()

        return subject, sender, date_str, body

    except Exception as e:
        print(f"⚠ Ошибка парсинга письма: {str(e)}")
        return None, None, None, None

# Обработка одного письма
def process_email(mail, email_id):
    try:
        msg_data = fetch_email_data(mail, email_id)

        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                subject, sender, date_str, body = parse_email(msg)

                if not subject or not sender or not body:
                    continue

                sent_at = parse_email_date(date_str)


                analyze_email_content(subject, sender, body, sent_at)

    except Exception:
        traceback.print_exc()

def get_emails(user_email, user_password, chat_id=None):
    """Парсит почту и отправляет процент выполнения в Telegram"""
    clear_database()  # Очищаем базу перед парсингом

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(user_email, user_password)
    mail.select("inbox")

    status, messages = mail.search(None, "ALL")
    email_ids = messages[0].split()
    total_emails = len(email_ids)  # Всего писем
    processed_emails = 0  # Счётчик обработанных писем

    print(f"✅ Найдено писем: {total_emails}")

    if chat_id:
        bot.send_message(chat_id, f"📩 Найдено писем: {total_emails}\nНачинаю обработку...")

    for index, email_id in enumerate(email_ids, start=1):
        process_email(mail, email_id)  # Обрабатываем письмо
        processed_emails += 1

        # Вычисляем процент выполнения
        percent_complete = int((processed_emails / total_emails) * 100)

        # Отправляем обновление каждые 10%
        if (percent_complete % 10 == 0 or processed_emails == total_emails) and percent_complete > 0:
            message = f"📊 Выполнено: {percent_complete}% ({processed_emails}/{total_emails})"
            print(message)
            if chat_id:
                bot.send_message(chat_id, message)

    mail.logout()

    if chat_id:
        bot.send_message(chat_id, "✅ Парсинг завершен! Данные сохранены в базе.")



def extract_name_from_email(email_body):
    try:
        client = OpenAI()  # Создаём клиент OpenAI

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system",
                 "content": "You are an assistant who extracts the sender's name from the text of the letter.."},
                {"role": "user",
                 "content": f"There is a text from the mail:\n{email_body}\n\nWhat is the sender's name? Write only sender's name without other words. If there is no name, write 'Unknown'."}
            ],
            temperature=0
        )

        name = response.choices[0].message.content.strip()
        return name if name else "Unknown"

    except Exception as e:
        print(f"⚠ Error while getting ChatGPT: {str(e)}")
        return "Unknown"


FORM_URL_USER = "https://docs.google.com/forms/d/e/1FAIpQLSfLwHTYqURZuf0PeyF65A6Je9zzlKZF2nhihCe_OLs2Ujls8g/formResponse"
FORM_URL_AUTO = "https://docs.google.com/forms/d/e/1FAIpQLSdw1tpeSzQ1cXf9GzUV6WXhluHLH67b6IW35739ZKgvTTyqOw/formResponse"

FORM_FIELDS = {
    "sent_at": "entry.1254920258",
    "sender_name": "entry.831907760",
    "sender_email": "entry.2137566045",
    "content": "entry.582710391"
}

def send_to_google_forms(sent_at, sender_name, sender_email, content, auto_gen=True):
    data = {
        FORM_FIELDS["sent_at"]: sent_at,
        FORM_FIELDS["sender_name"]: sender_name,
        FORM_FIELDS["sender_email"]: sender_email,
        FORM_FIELDS["content"]: content
    }
    if auto_gen is True:
        response = requests.post(FORM_URL_AUTO, data=data)
    elif auto_gen is False:
        response = requests.post(FORM_URL_USER, data=data)

    if response.status_code == 200:
        print("✅ Данные успешно отправлены в Google Sheets через Google Forms")
    else:
        print(f"⚠ Ошибка при отправке: {response.status_code}")

def export_mails_to_google_forms():
    """Экспортирует все данные из базы в Google Forms"""
    # Загружаем новости из базы
    auto_news = AutoNews.objects.all().values_list("sent_at", "sender_name", "sender_email", "content")
    user_news = UserNews.objects.all().values_list("sent_at", "sender_name", "sender_email", "content")

    # Отправляем каждую новость
    for news in auto_news:
        send_to_google_forms(*news, auto_gen=True)
    for news in user_news:
        send_to_google_forms(*news, auto_gen=False)

    print("✅ Все данные отправлены в Google Forms!")




def clear_database():
    """Удаляет все записи из моделей AutoNews и UserNews"""
    AutoNews.objects.all().delete()
    UserNews.objects.all().delete()
    print("✅ База данных очищена перед новым парсингом.")


