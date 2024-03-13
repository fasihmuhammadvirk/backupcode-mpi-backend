import time
import imaplib
import email
import os
from mpi_backend.config import SMTP_SERVER, LOGIN_EMAIL, LOGIN_PWD


def login():
    mail = imaplib.IMAP4_SSL(SMTP_SERVER)
    mail.login(LOGIN_EMAIL, LOGIN_PWD)
    mail.select('inbox')
    print("Connection to mail box established.\n")
    return mail


def search_new_emails(mail):
    result, data = mail.search(None, 'UNSEEN')

    for num in data[0].split():
        result, data = mail.fetch(num, '(RFC822)')
        raw_email = data[0][1]

        msg = email.message_from_bytes(raw_email)

        for part in msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            if part.get('Content-Disposition') is None:
                continue

            filename = part.get_filename()

            if filename:
                print(f'Downloading Invoice {filename}')
                filepath = os.path.join('mpi_backend/storage', filename)
                with open(filepath, 'wb') as f:
                    f.write(part.get_payload(decode=True))


def email_download_background_task():
    mail = login()
    search_new_emails(mail)
