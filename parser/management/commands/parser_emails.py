import imaplib
import email
import re
from datetime import datetime
from email.header import decode_header
import requests
import spacy
from parser.models import AutoNews, UserNews

# Учетные данные
IMAP_SERVER = "imap.gmail.com"
nlp = spacy.load("en_core_web_sm")


def analyze_email_content(subject, sender, body, sent_at):
    """Анализ письма и сохранение его в соответствующую модель Django."""
    print(f"Тема: {subject}")
    print(f"Отправитель: {sender}")
    print(f"Время отправки: {sent_at}")

    is_automated = False

    # Извлечение sender_name и sender_email
    sender_name, sender_email = extract_sender_info(sender)

    # Проверка на no-reply
    if sender_email and "no-reply" in sender_email.lower():
        print("Письмо отправлено с no-reply адреса (автоматическое письмо).")
        is_automated = True

    # Проверка на слово unsubscribe
    if "unsubscribe" in body.lower():
        print("Письмо содержит слово 'unsubscribe' (вероятно, рассылка).")
        is_automated = True

    # Проверка на шаблонные фразы
    automated_phrases = [
        "do not reply", "automated message", "click here",
        "manage your preferences", "update your settings"
    ]
    for phrase in automated_phrases:
        if phrase in body.lower():
            print(f"Письмо содержит шаблонную фразу: '{phrase}' (вероятно, рассылка).")
            is_automated = True

    # Проверка на наличие HTML
    if re.search(r"<html>|<body>|<div>", body, re.IGNORECASE):
        print("Письмо содержит HTML-разметку (вероятно, автоматическое письмо).")
        is_automated = True

    # Сохранение в базу данных
    if is_automated:
        save_auto_news(sender_name, sender_email, body, sent_at)
    else:
        save_user_news(sender_name, sender_email, body, sent_at)

    print("=" * 50)


def extract_sender_info(sender):
    """Извлекает имя отправителя и email из строки 'From'."""
    match = re.match(r'(?:"?([^"]*)"?\s)?(?:<?([\w\.-]+@[\w\.-]+)>?)', sender)
    if match:
        sender_name = match.group(1) if match.group(1) else match.group(2)
        sender_email = match.group(2)
        return sender_name, sender_email
    return sender, sender


def parse_email_date(date_str):
    """Парсит строку даты из заголовка Email и возвращает объект datetime."""
    try:
        return datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")  # Формат даты в заголовках email
    except Exception:
        return None


def save_auto_news(sender_name, sender_email, content, sent_at):
    """Сохраняет автоматическое письмо в AutoNews."""
    news = AutoNews(sender_name=sender_name, sender_email=sender_email, content=content, sent_at=sent_at)
    news.save()
    print("✅ Автоматическая новость сохранена в AutoNews")


def save_user_news(sender_name, sender_email, content, sent_at):
    """Сохраняет письмо от реального человека в UserNews."""
    news = UserNews(sender_name=sender_name, sender_email=sender_email, content=content, sent_at=sent_at)
    news.save()
    print("✅ Новость от реального человека сохранена в UserNews")


def get_html_emails(user_email, user_password):
    """Подключается к Gmail и обрабатывает входящие письма."""
    # Подключение к серверу
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(user_email, user_password)

    # Выбор папки "Входящие"
    mail.select("inbox")

    # Поиск писем (в данном случае – все)
    status, messages = mail.search(None, "ALL")
    email_ids = messages[0].split()

    print(f"Найдено писем: {len(email_ids)}")

    # Чтение последних 20 писем
    for email_id in email_ids[-20:]:
        # Получение данных письма
        status, msg_data = mail.fetch(email_id, "(RFC822)")

        for response_part in msg_data:
            if isinstance(response_part, tuple):
                # Парсинг сообщения
                msg = email.message_from_bytes(response_part[1])

                # Декодирование заголовков
                subject, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding if encoding else "utf-8")
                sender = msg.get("From")

                # Парсинг времени отправки письма
                date_str = msg["Date"]
                sent_at = parse_email_date(date_str)

                # Если письмо содержит HTML
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))

                        # Получение HTML или текстовой версии письма
                        if content_type == "text/plain" and "attachment" not in content_disposition:
                            body = part.get_payload(decode=True).decode()
                            break
                        elif content_type == "text/html":
                            body = part.get_payload(decode=True).decode()
                            break
                else:
                    # Если письмо не мультичастное
                    content_type = msg.get_content_type()
                    if content_type == "text/plain" or content_type == "text/html":
                        body = msg.get_payload(decode=True).decode()

                # Анализ письма
                analyze_email_content(subject, sender, body, sent_at)

    # Закрытие соединения
    mail.logout()


# 🔗 ВАЖНО: Укажите URL вашей Google Формы (замените!)
FORM_URL_USER = "https://docs.google.com/forms/d/e/1FAIpQLSfLwHTYqURZuf0PeyF65A6Je9zzlKZF2nhihCe_OLs2Ujls8g/formResponse"
FORM_URL_AUTO = "https://docs.google.com/forms/d/e/1FAIpQLSdw1tpeSzQ1cXf9GzUV6WXhluHLH67b6IW35739ZKgvTTyqOw/formResponse"

# 📝 Укажите `entry.XYZ` из вашей Google Формы
FORM_FIELDS = {
    "sent_at": "entry.1254920258",
    "sender_name": "entry.831907760",
    "sender_email": "entry.2137566045",
    "content": "entry.582710391"
}

def send_to_google_forms(sent_at, sender_name, sender_email, content, auto_gen=True):
    """Отправляет данные в Google Forms"""
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

def export_news_to_google_forms():
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


