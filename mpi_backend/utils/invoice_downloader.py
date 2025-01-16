import time
import imaplib
import email
import os,re
from pathlib import Path
from email.utils import parsedate_to_datetime
import pytz
import email
import logging
logger = logging.getLogger(__name__)


from mpi_backend.config import SMTP_SERVER, LOGIN_EMAIL, LOGIN_PWD, INVOICE_DOWNLOAD_FOLDER, SUPPLIERS,TIMEZONE
from datetime import datetime, timedelta

from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.utils.invoice_convertor import convert_invoice

EXCLUDED_SENDERS = [ # suppliers whose emails are to be marked as read after downloading
    "info@wwps.co",
    "bmwpsupply@gmail.com",
    "billing@ysplumbing.com",
    "accounting@supremeplumbingnj.com",
    "orders@supremeplumbingnj.com",
    "billing@pyramidps.com",
    "purchasing@pyramidps.com",
    "donotreply@brucesupply.net",
    "donotreply@certifiedlumber.com",
    "breindy@parkplumbingsupply.com",
    "accounting@kjpsinc.com",
    "nefcocorp@billtrust.com",
    "timsfile@awisco.net",
    "billing@afsupply.com",
    "billing@sparkleening.com",
    "billing@positive.tech",
    "ar@opusoperations.com",
    "donotreply@cardknox.com",
    "billing@flowmarksupply.com",
    "mendy@flowmarksupply.com",
    "billing@mpiplumbingcorp.com",
    "Info@wwps.co"
]


def login():
    mail = imaplib.IMAP4_SSL(SMTP_SERVER)
    mail.login(LOGIN_EMAIL, LOGIN_PWD)
    mail.select('inbox')
    logger.info("Connection to mail box established.\n")
    return mail


def filter_by_time(email_ids, reference_time, mail):
    """
    No direct filtering by time is supported by imaplib, only filter by data is supported.
    So, we are filtering by time based on custom logic.
    email_ids-> All unseen emails received today
    reference_time -> Time when the task was triggered minus 25 minutes.
    """
    emails_info = []
    for email_id in email_ids:
        try:
            result, email_data = mail.uid('fetch', email_id, '(RFC822)')
            raw_email = email_data[0][1]
            msg = email.message_from_bytes(raw_email)

            if len(msg['Date']) == 37:
                email_sent_time = msg['Date'][:-12] # Remove the timezone info (+0000) or (-0700 PDT)
            else:
                email_sent_time = msg['Date'][:-6]

            if re.match(r'\A[a-zA-Z]{3},', email_sent_time):  # handling multiple date formats coming from gmail
                email_sent_time = datetime.strptime(email_sent_time, '%a, %d %b %Y %H:%M:%S')
            else:
                email_sent_time = datetime.strptime(email_sent_time, '%d %b %Y %H:%M:%S')
            email_sent_time = TIMEZONE.localize(email_sent_time)

            time_difference = reference_time - email_sent_time
            if time_difference.total_seconds() <= 1500:  # 25 minutes in seconds
                emails_info.append(email_id)

        except Exception as e:
            logger.error(type(e).__name__,
                  e.__traceback__.tb_lineno, "Exception with date-time format")
    return emails_info


def search_new_emails(mail):
    time_frame = datetime.now(TIMEZONE).strftime('%d-%b-%Y')  #unseen emails for current day & than manually filter them later based on time
    result, data = mail.uid('search', None, f'(SINCE "{time_frame}")')
    email_ids = data[0].split()
    filtered_email_ids = []
    for email_id in email_ids:
        result, msg_data = mail.uid('fetch', email_id, '(BODY.PEEK[HEADER.FIELDS (FROM)])')
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)
        from_email = email.utils.parseaddr(msg['From'])[1]
        # Check if the email is from the excluded senders list
        if from_email in EXCLUDED_SENDERS:
            filtered_email_ids.append(email_id)
    return filtered_email_ids


def download_email_attachments(email_message, base_folder_path):
    for part in email_message.walk():
        part.get_payload()
        if ((part.get_content_maintype() != 'multipart' and part.get('Content-Disposition') is not None) or
                ('customer of World Wide' in part.get_payload())): # for WWPS 'Content-Disposition' is None, so a separate condition
            email_date = email_message['Date']
            date_time_obj = parsedate_to_datetime(email_date)

            # creating directory structure
            inner_dir = f'{str(date_time_obj.month)}-{str(date_time_obj.day)}-{str(date_time_obj.year)}'

            try:
                supplier_name = get_supplier(email_message['subject'], supplier_email=email_message['Return-Path'])
            except:
                logger.error(f"Couldn't detect supplier for email -> {str(email_message['subject'])}. Skipping Email.")
                continue

            supplier_path = os.path.join(base_folder_path,supplier_name)  # base folder (to-from dates) + supplier name
            if not os.path.isdir(supplier_path): os.mkdir(supplier_path)
            inner_dir = os.path.join(supplier_path, inner_dir)
            if not os.path.isdir(inner_dir): os.mkdir(inner_dir)

            try:
                # saving the attachment
                filepath = os.path.join(inner_dir, part.get_filename())
            except: continue

            if part.get_payload(decode=True) is None: continue

            if not (filepath.endswith('.pdf') or filepath.endswith('.PDF')): continue

            try:
                with open(filepath, 'wb') as f:
                    f.write(part.get_payload(decode=True))
                    logger.info(f"Downloaded {part.get_filename()} , saved at {filepath}")
            except:
                continue  # invalid file name


def get_supplier(email_subject, supplier_email) -> str:
    if "statement" in email_subject.lower(): return "no_supplier"
    if "bmw" in email_subject.lower(): return SUPPLIERS[0]
    elif "world wide" in email_subject.lower(): return SUPPLIERS[1]
    elif "y&s" in email_subject.lower(): return SUPPLIERS[2]
    elif "invoice # i-" in email_subject.lower() or "supreme plumbing" in email_subject.lower(): return SUPPLIERS[3]
    elif "pyramid plumbing invoice" in email_subject.lower(): return SUPPLIERS[4]
    elif "abc opus services" in email_subject.lower(): return SUPPLIERS[5]
    elif "park plumbing & heating supply - invoices overnight" in email_subject.lower(): return SUPPLIERS[6]
    elif "webb payment receipt" in email_subject.lower(): return SUPPLIERS[8]
    elif "see invoice i-" in email_subject.lower(): return SUPPLIERS[9]
    else: return "no_supplier"


def email_download_background_task():
    # folder naming structure is 'current date & time minus 3 minutes -> current date & time'
    base_folder = f"{(datetime.now(TIMEZONE) - timedelta(minutes=3)).strftime('%d-%b-%Y_%H-%M-%S')} - {datetime.now(TIMEZONE).strftime('%d-%b-%Y_%H-%M-%S')}"
    base_folder_path = os.path.join(Path(INVOICE_DOWNLOAD_FOLDER), base_folder)
    if not os.path.isdir(base_folder_path): os.mkdir(base_folder_path)

    logger.info(f"Email Download Background Task Triggered >>> {base_folder}")

    mail = login()
    email_ids = search_new_emails(mail)

    email_ids = filter_by_time(email_ids,(datetime.now(TIMEZONE) - timedelta(minutes=3)),mail)

    for e_id in email_ids:
        _, response = mail.uid('fetch', e_id, '(BODY.PEEK[])')
        if response[0] is None : continue
        raw_email = response[0][1].decode('utf-8')
        email_message = email.message_from_string(raw_email)
        download_email_attachments(email_message, base_folder_path)

        try: # check if it is invoice, if it is not mark emails as unread
            subject = email_message['subject'].lower() if email_message['subject'] else ""
            in_reply_to = email_message['In-Reply-To']
            references = email_message['References']

            is_thread = bool(in_reply_to or references) # Check if the email is part of a thread or not

            if is_thread or not any(keyword in subject for keyword in ['invoice', 'invoices']): # Mark email as unread if it's part of a thread or doesn't contain specific keywords
                mail.uid('store', e_id, '-FLAGS', '(\Seen)')
        except: pass

    # trigger remaining two tasks
    converted_files, failed_files = convert_invoice(base_folder)
    logger.info(f"Convert to excel task is finished.\n Converted files ->{converted_files} \n Failed Files -> {failed_files}")
    process_extracted_data(converted_files, failed_files)
