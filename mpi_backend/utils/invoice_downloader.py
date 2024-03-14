import time
import imaplib
import email
import os
from pathlib import Path
from email.utils import parsedate_to_datetime

from mpi_backend.config import SMTP_SERVER, LOGIN_EMAIL, LOGIN_PWD, INVOICE_DOWNLOAD_FOLDER, SUPPLIERS
from datetime import datetime, timedelta


def login():
    mail = imaplib.IMAP4_SSL(SMTP_SERVER)
    mail.login(LOGIN_EMAIL, LOGIN_PWD)
    mail.select('inbox')
    print("Connection to mail box established.\n")
    return mail


def search_new_emails(mail):
    time_frame = (datetime.now() - timedelta(days=3)).strftime('%d-%b-%Y')  # unseen emails since last three days
    result, data = mail.uid('search', None, '(UNSEEN SINCE {0})'.format(time_frame))

    email_ids = data[0].split()
    return email_ids


def download_email_attachments(email_message, base_folder_path):
    for part in email_message.walk():
        if part.get_content_maintype() != 'multipart' and part.get('Content-Disposition') is not None:
            email_date = email_message['Date']
            date_time_obj = parsedate_to_datetime(email_date)

            # creating directory structure
            inner_dir = f'{str(date_time_obj.month)}-{str(date_time_obj.day)}-{str(date_time_obj.year)}'

            try:
                if 'Supreme Plumbing Supply' in part.get_filename() or 'Invoice_I' in part.get_filename():  # could not be extracted from email subject
                    supplier_name = SUPPLIERS[3]
                else:
                    supplier_name = get_supplier(email_message['subject'], supplier_email=email_message['Return-Path'])
            except:
                continue

            supplier_path = os.path.join(base_folder_path,supplier_name)  # base folder (to-from dates) + supplier name
            if not os.path.isdir(supplier_path): os.mkdir(supplier_path)
            inner_dir = os.path.join(supplier_path, inner_dir)
            if not os.path.isdir(inner_dir): os.mkdir(inner_dir)

            # saving the attachment
            filepath = os.path.join(inner_dir, part.get_filename())
            if part.get_payload(decode=True) is None: continue

            if not (filepath.endswith('.pdf') or filepath.endswith('.PDF')): continue

            try:
                with open(filepath, 'wb') as f:
                    f.write(part.get_payload(decode=True))
                    print(f"Downloaded {part.get_filename()} , saved at {filepath}")
            except:
                continue  # invalid file name


def get_supplier(email_subject, supplier_email) -> str:
    if "bmw" in email_subject.lower(): return SUPPLIERS[0]
    elif "world wide" in email_subject.lower(): return SUPPLIERS[1]
    elif "y&s" in email_subject.lower(): return SUPPLIERS[2]
    elif "pyramid plumbing invoice" in email_subject.lower(): return SUPPLIERS[4]
    elif "abc opus services" in email_subject.lower(): return SUPPLIERS[5]
    elif "park plumbing & heating supply - invoices overnight" in email_subject.lower(): return SUPPLIERS[6]
    elif "webb payment receipt" in email_subject.lower(): return SUPPLIERS[8]
    elif "invoice:" in email_subject.lower() and "p/o:" in email_subject.lower(): return SUPPLIERS[9]
    elif "mpiplu invoice" in email_subject.lower(): return 'Certified Lumber'
    elif "kj plumbing sales inc - invoices" in email_subject.lower(): return SUPPLIERS[11]
    elif "acct no. 133588: your invoice" in email_subject.lower(): return SUPPLIERS[12]
    elif "invoice" in email_subject.lower() and 'for' in email_subject.lower(): return SUPPLIERS[13]
    elif "invoice" in email_subject.lower() and 'from positive computer services' in email_subject.lower(): return SUPPLIERS[16]
    elif email_subject.lower() == "invoices": return SUPPLIERS[17]

    else: return "no_supplier"


def email_download_background_task():

    base_folder = f"{(datetime.now() - timedelta(days=3)).strftime('%d-%m-%Y')} - {datetime.now().strftime('%d-%m-%Y')}"
    base_folder_path = os.path.join(Path(INVOICE_DOWNLOAD_FOLDER), base_folder)
    if not os.path.isdir(base_folder_path): os.mkdir(base_folder_path)

    mail = login()
    email_ids = search_new_emails(mail)

    for e_id in email_ids:
        _, response = mail.uid('fetch', e_id, '(BODY.PEEK[])')
        if response[0] is None : continue
        raw_email = response[0][1].decode('utf-8')
        email_message = email.message_from_string(raw_email)
        download_email_attachments(email_message, base_folder_path)
