import imaplib
import email
import re
import traceback
from datetime import datetime
from email.header import decode_header
import requests
import spacy
from openai import OpenAI
import chardet

from parser.bot_instance import bot


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

    if is_automated:
        send_to_google_forms(sent_at, sender_name, sender_email, body, auto_gen=True)
    else:
        sender_name = extract_name_from_email(body, sender_name, sender_email)
        print(f"🎯 Извлеченное имя: {sender_name}")

        send_to_google_forms(sent_at, sender_name, sender_email, body, auto_gen=False)

    print("=" * 50)
    return is_automated


def extract_sender_info(sender):
    match = re.match(r'(?:"?([^"]*)"?\s)?(?:<?([\w\.-]+@[\w\.-]+)>?)', sender)
    if match:
        sender_name = match.group(1) if match.group(1) else match.group(2)
        sender_email = match.group(2)
        return sender_name, sender_email
    return sender, sender


def parse_email_date(date_str):
    try:
        return datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
    except Exception:
        return None


# Получение данных письма
def fetch_email_data(mail, email_id):
    status, msg_data = mail.fetch(email_id, "(RFC822)")
    return msg_data


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

                if content_type in ["text/plain", "text/html"] and "attachment" not in content_disposition:
                    try:
                        raw_payload = part.get_payload(decode=True)

                        detected_encoding = chardet.detect(raw_payload)["encoding"]

                        body = raw_payload.decode(detected_encoding if detected_encoding else "utf-8", errors="ignore")

                    except Exception as e:
                        print(f"⚠ Ошибка декодирования тела письма: {str(e)}")
                    break
        else:
            content_type = msg.get_content_type()
            if content_type in ["text/plain", "text/html"]:
                try:
                    raw_payload = msg.get_payload(decode=True)
                    detected_encoding = chardet.detect(raw_payload)["encoding"]
                    body = raw_payload.decode(detected_encoding if detected_encoding else "utf-8", errors="ignore")
                except Exception as e:
                    print(f"⚠ Ошибка декодирования тела письма: {str(e)}")

        return subject, sender, date_str, body

    except Exception as e:
        print(f"⚠ Ошибка парсинга письма: {str(e)}")
    return None, None, None, None


def process_email(mail, email_id):
    is_automated = False
    try:
        msg_data = fetch_email_data(mail, email_id)

        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                subject, sender, date_str, body = parse_email(msg)

                if not subject or not sender or not body:
                    continue

                sent_at = parse_email_date(date_str)


                is_automated = analyze_email_content(subject, sender, body, sent_at)

    except:
        traceback.print_exc()

    return is_automated




def get_emails(user_email, user_password, chat_id=None):
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(user_email, user_password)
    mail.select("inbox")

    status, messages = mail.search(None, "ALL")
    email_ids = messages[0].split()

    print(f"✅ Найдено писем: {len(email_ids)}")
    if chat_id:
        bot.send_message(chat_id, f"📩 Найдено писем: {len(email_ids)}\nФильтрую письма...")

    last_emails = filter_duplicates(email_ids, mail)
    total_emails = len(last_emails)

    print(f"✅ После фильтрации осталось {total_emails} писем")
    if chat_id:
        bot.send_message(chat_id, f"📩 После фильтрации осталось {total_emails} писем")

    processed_emails = 0
    last_reported_percent = 0

    auto_mails = 0
    user_mails = 0

    for index, email_id in enumerate(last_emails.values(), start=1):
        is_automated = process_email(mail, email_id)
        processed_emails += 1

        if is_automated is True:
            auto_mails += 1
        elif is_automated is False:
            user_mails += 1

        percent_complete = int((processed_emails / total_emails) * 100)

        if percent_complete >= last_reported_percent + 10:
            message = f"📊 Выполнено: {percent_complete}% ({processed_emails}/{total_emails})"
            print(message)
            if chat_id:
                bot.send_message(chat_id, message)

            last_reported_percent = percent_complete

    mail.logout()

    final_message = (
        f"✅ Парсинг завершен!\n"
        f"📨 Всего обработано писем: {total_emails}\n"
        f"🤖 Автоматические письма: {auto_mails}\n"
        f"👤 Пользовательские письма: {user_mails}"
    )

    print(final_message)

    if chat_id:
        bot.send_message(chat_id, final_message)


def filter_duplicates(email_ids, mail):
    last_emails = {}

    for email_id in email_ids:
        msg_data = fetch_email_data(mail, email_id)

        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                _, sender, _, _ = parse_email(msg)

                if sender:
                    last_emails[sender] = email_id

    return last_emails


def extract_name_from_email(email_body, sender_name, sender_email):
    try:
        client = OpenAI()

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system",
                 "content": "You are an advanced AI assistant that extracts the sender's name from an email. "
                            "Your response must contain ONLY the sender's name and nothing else. "
                            "Follow these strict rules when extracting the name:"},

                {"role": "user",
                 "content": f"""There is an email with the following content:

                ------------------------------
                **Sender Name (from Google Account):** {sender_name}  
                **Sender Email Address:** {sender_email}  
                **Email Body:**  
                {email_body}
                ------------------------------

                **Extraction Rules:**
                1️⃣ **First, analyze the sender's name from the Google Account.** If it contains a **real person’s name or company name**, return it exactly as is.  
                2️⃣ If the sender’s name is **nonsensical, random characters, an email address, or clearly not a human/company name**, ignore it.  
                3️⃣ **Check the email body.** If the sender explicitly states their name (e.g., ‘Best regards, John Doe’), return only the name.  
                4️⃣ **Ignore the recipient’s name.** If the email starts with something like "Hi Julia", **Julia is NOT the sender's name.**  
                5️⃣ **If the sender’s name is still unclear, look for a company name.** If a company is mentioned as the sender, return its name.  
                6️⃣ **If no valid name is found, return `"Their"`**.  

                **Important Output Rules:**
                - Respond with ONLY the extracted sender's name (without extra words like "The sender's name is...").  
                - Do NOT add punctuation, quotes, or any explanation.  
                - If you determine the name is invalid or missing, return exactly: `"Their"`  

                What is the sender's name according to these rules?"""
                 }
            ],
            temperature=0
        )

        name = response.choices[0].message.content.strip()
        return name if name else "Their"

    except Exception as e:
        print(f"⚠ Error while getting ChatGPT: {str(e)}")
        return "Their"


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



