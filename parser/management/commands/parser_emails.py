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

    if sender_email and ("no-reply" or "noreply") in sender_email.lower():
        is_automated = True

    if "unsubscribe" in body.lower():
        is_automated = True

    automated_phrases = [
        "do not reply", "automated message", "click here",
        "manage your preferences", "update your settings", "do not respond", "google"
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
        phone = extract_phone_from_email(body, sender_name, sender_email)
        domain = extract_website_from_email(body, sender_name, sender_email)
        company_name = extract_company_name_from_email(body, sender_name, sender_email)
        send_to_google_forms(
            sent_at,
            sender_name,
            sender_email,
            body,
            tel=phone,
            domain=domain,
            company_name=company_name,
            auto_gen=False
        )

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
    """Обрабатывает одно письмо, используя переданное IMAP-соединение"""
    try:
        status, msg_data = mail.fetch(email_id, "(RFC822)")
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                subject, sender, date_str, body = parse_email(msg)

                if not subject or not sender or not body:
                    return False

                sent_at = parse_email_date(date_str)
                is_automated = analyze_email_content(subject, sender, body, sent_at)

                return is_automated

    except Exception as e:
        print(f"⚠ Ошибка при обработке письма {email_id}: {str(e)}")

    return False  # Если письмо не удалось обработать, считаем его пользовательским


def get_emails(user_email, user_password, chat_id=None):
    """Парсит почту, открывая IMAP-соединение каждые 100 писем"""

    try:
        # 1️⃣ Подключаемся к Gmail
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(user_email, user_password)
        mail.select("inbox")

        # 2️⃣ Получаем список всех писем
        status, messages = mail.search(None, "ALL")
        email_ids = messages[0].split()

        print(f"✅ Найдено писем: {len(email_ids)}")
        if chat_id:
            bot.send_message(chat_id, f"📩 Найдено писем: {len(email_ids)}\nФильтрую письма...")

        # 3️⃣ Фильтруем дубликаты, оставляя только последнее письмо от каждого отправителя
        last_emails = filter_duplicates(email_ids, mail)
        total_emails = len(last_emails)

        print(f"✅ После фильтрации осталось {total_emails} писем")
        if chat_id:
            bot.send_message(chat_id, f"📩 После фильтрации осталось {total_emails} писем")

    except Exception as e:
        print(f"⚠ Ошибка при подключении к Gmail: {str(e)}")
        if chat_id:
            bot.send_message(chat_id, f"⚠ Ошибка подключения к Gmail: {str(e)}")
        return

    finally:
        # ✅ Закрываем IMAP-соединение после фильтрации
        try:
            mail.close()
            mail.logout()
        except:
            pass

    # 4️⃣ Обрабатываем письма (открывая IMAP каждые 100 писем)
    processed_emails = 0
    last_reported_percent = 0
    auto_mails = 0
    user_mails = 0

    email_list = list(last_emails.values())  # Преобразуем dict_values в список

    for start_index in range(0, total_emails, 100):  # Обрабатываем письма пакетами по 100
        try:
            # ✅ Открываем IMAP-соединение перед обработкой 100 писем
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(user_email, user_password)
            mail.select("inbox")

            for index in range(start_index, min(start_index + 100, total_emails)):
                email_id = email_list[index]
                is_automated = process_email(mail, email_id)  # Передаем IMAP-соединение

                processed_emails += 1
                if is_automated:
                    auto_mails += 1
                else:
                    user_mails += 1

                percent_complete = int((processed_emails / total_emails) * 100)

                # ✅ Обновление статуса раз в 10% или через каждые 50 писем
                if percent_complete >= last_reported_percent + 10 or processed_emails % 50 == 0:
                    message = f"📊 Выполнено: {percent_complete}% ({processed_emails}/{total_emails})"
                    print(message)
                    if chat_id:
                        bot.send_message(chat_id, message)

                    last_reported_percent = percent_complete

        except Exception as e:
            print(f"⚠ Ошибка при обработке писем: {str(e)}")
            if chat_id:
                bot.send_message(chat_id, f"⚠ Ошибка при обработке писем: {str(e)}")

        finally:
            # ✅ Закрываем IMAP-соединение после обработки 100 писем
            try:
                mail.close()
                mail.logout()
            except:
                pass

    # ✅ Финальное сообщение с результатами
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



def extract_company_name_from_email(email_body, sender_name, sender_email):
    try:
        client = OpenAI()

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system",
                 "content": "You are an advanced AI assistant that extracts the sender's company name from an email. "
                            "Your response must contain ONLY the company name and nothing else. "
                            "Follow these strict rules when extracting the company name:"},

                {"role": "user",
                 "content": f"""There is an email with the following content:

                ------------------------------
                **Sender Name (from Google Account):** {sender_name}  
                **Sender Email Address:** {sender_email}  
                **Email Body:**  
                {email_body}
                ------------------------------

                **Extraction Rules:**
                1️⃣ Try to find the company name in the **email body**, especially in the signature or footer.  
                2️⃣ If the sender's name (from the Google Account) looks like a **company name**, use it.  
                3️⃣ Do NOT confuse the recipient's company or referenced clients/partners with the sender’s company.  
                4️⃣ If multiple companies are mentioned, choose the one clearly associated with the sender.  
                5️⃣ If no valid company name is found, return exactly: `"No company"`

                **Important Output Rules:**
                - Respond with ONLY the company name (e.g., `Acme Corp`)  
                - Do NOT add punctuation, quotes, or any explanation  
                - If no valid company is found, return exactly: `"No company"`

                What is the sender's company name according to these rules?"""
                 }
            ],
            temperature=0
        )

        company = response.choices[0].message.content.strip()
        return company if company else "No company"

    except Exception as e:
        print(f"⚠ Error while getting ChatGPT: {str(e)}")
        return "No company"


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


def extract_website_from_email(email_body, sender_name, sender_email):
    try:
        client = OpenAI()

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system",
                 "content": "You are an advanced AI assistant that extracts the sender's company website from an email. "
                            "Your response must contain ONLY the website URL and nothing else. "
                            "Follow these strict rules when extracting the website:"},

                {"role": "user",
                 "content": f"""There is an email with the following content:

                ------------------------------
                **Sender Name (from Google Account):** {sender_name}  
                **Sender Email Address:** {sender_email}  
                **Email Body:**  
                {email_body}
                ------------------------------

                **Extraction Rules:**
                1️⃣ Look for a **valid website URL** in the email body (e.g., https://example.com or www.example.com).
                2️⃣ If multiple websites are mentioned, return the **first one** that looks like the sender's/company's site.
                3️⃣ If there is no website address in the text of the letter, but it can be taken from the sender - do it.
                4️⃣ Ignore links to Gmail, LinkedIn, Facebook, Instagram, Twitter, and other social platforms unless clearly the main company site.
                5️⃣ If no valid website is found, return exactly: `"No website"`

                **Important Output Rules:**
                - Respond with ONLY the website URL (e.g., `https://example.com`)
                - Do NOT add quotes, labels, or explanation  
                - If no valid website is found, return exactly: `"No website"`

                What is the sender's company website according to these rules?"""
                 }
            ],
            temperature=0
        )

        website = response.choices[0].message.content.strip()
        return website if website else "No website"

    except Exception as e:
        print(f"⚠ Error while getting ChatGPT: {str(e)}")
        return "No website"


def extract_phone_from_email(email_body, sender_name, sender_email):
    try:
        client = OpenAI()

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system",
                 "content": "You are an advanced AI assistant that extracts the sender's phone number from an email. "
                            "Your response must contain ONLY the phone number and nothing else. "
                            "Follow these strict rules when extracting the phone number:"},

                {"role": "user",
                 "content": f"""There is an email with the following content:

                ------------------------------
                **Sender Name (from Google Account):** {sender_name}  
                **Sender Email Address:** {sender_email}  
                **Email Body:**  
                {email_body}
                ------------------------------

                **Extraction Rules:**
                1️⃣ Look for a phone number in the **email body**. It may appear in the signature or body content.
                2️⃣ Prefer numbers that look like they are **mobile or personal contact numbers**, not generic support hotlines.
                3️⃣ Accept international formats (e.g., +1 234-567-8901), local formats (e.g., (234) 567-8901), or plain (e.g., 2345678901).
                4️⃣ If there are **multiple numbers**, return only the **first valid one** found.
                5️⃣ If no phone number is found, return exactly: `"No phone"`

                **Important Output Rules:**
                - Respond with ONLY the phone number (e.g., `+1 234-567-8901`)  
                - Do NOT add punctuation, quotes, labels, or any explanation.  
                - If no valid number is found, return exactly: `"No phone"`

                What is the sender's phone number according to these rules?"""
                 }
            ],
            temperature=0
        )

        phone = response.choices[0].message.content.strip()
        return phone if phone else "No phone"

    except Exception as e:
        print(f"⚠ Error while getting ChatGPT: {str(e)}")
        return "No phone"


FORM_URL_USER = "https://docs.google.com/forms/u/0/d/e/1FAIpQLScO2cwZOFXMC_sDW9KpiIq6uRu0J7J09AcmWYULq9YrMt9APQ/formResponse"
FORM_URL_AUTO = "https://docs.google.com/forms/u/0/d/e/1FAIpQLSdMzPFzLkEl9qtettxZF62YtU5J8lJs0kqv9v7r5wOPPnloyg/formResponse"

FORM_FIELDS = {
    "sent_at": "entry.1426032914",
    "sender_name": "entry.2025415057",
    "sender_email": "entry.1002659073",
    "content": "entry.1998393221",
    "domain": 'entry.1839279607',
    "company_name": 'entry.957860696',
    "tel": 'entry.175618447',
}


FORM_FIELDS_AUTO = {
    "sent_at": "entry.1939361135",
    "sender_name": "entry.253700324",
    "sender_email": "entry.1363315117",
    "content": "entry.1718382702",
    "domain": 'entry.1963539511',
    "company_name": 'entry.1656382618',
    "tel": 'entry.384050106',
}


def send_to_google_forms(sent_at, sender_name, sender_email, content, domain='', company_name='', tel='', auto_gen=True):
    if auto_gen is True:
        data = {
            FORM_FIELDS_AUTO["sent_at"]: sent_at,
            FORM_FIELDS_AUTO["sender_name"]: sender_name,
            FORM_FIELDS_AUTO["sender_email"]: sender_email,
            FORM_FIELDS_AUTO["content"]: content,
            FORM_FIELDS_AUTO["domain"]: domain,
            FORM_FIELDS_AUTO["company_name"]: company_name,
            FORM_FIELDS_AUTO["tel"]: tel,
        }
        response = requests.post(FORM_URL_AUTO, data=data)

    elif auto_gen is False:
        data = {
            FORM_FIELDS["sent_at"]: sent_at,
            FORM_FIELDS["sender_name"]: sender_name,
            FORM_FIELDS["sender_email"]: sender_email,
            FORM_FIELDS["content"]: content,
            FORM_FIELDS["domain"]: domain,
            FORM_FIELDS["company_name"]: company_name,
            FORM_FIELDS["tel"]: tel,
        }
        response = requests.post(FORM_URL_USER, data=data)

    if response.status_code == 200:
        print("✅ Данные успешно отправлены в Google Sheets через Google Forms")
    else:
        print(f"⚠ Ошибка при отправке: {response.status_code}")



