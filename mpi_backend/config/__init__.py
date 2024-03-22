import os
from pathlib import Path


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USERNAME = os.getenv("POSTGRES_USERNAME")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

SQLALCHEMY_DATABASE_URI = f"postgresql://{POSTGRES_USERNAME}:"\
    f"{POSTGRES_PASSWORD}@"\
    f"{POSTGRES_HOST}:"\
    f"{POSTGRES_PORT}/"\
    f"{POSTGRES_DB}"

SMTP_SERVER = os.getenv("SMTP_SERVER")
LOGIN_EMAIL = os.getenv("LOGIN_EMAIL")
LOGIN_PWD = os.getenv("LOGIN_PWD")
INVOICE_DOWNLOAD_FOLDER = os.getenv("INVOICE_DOWNLOAD_FOLDER", "mpi_backend/storage")

SUPPLIERS = ['BMW Plumbing Supplies', 'World Wide Plumbing', 'Y & S Plumbing Supply', 'Supreme Plumbing Supply',
             'Pyramid Plumbing', 'ABC Opus Services', 'Park Plumbing Supply', 'Gotham Plumbing Supply',
             'FW Webb Plumbing Supply','Bruce Supply','Boro Park & Certified Lumber', 'KJ Plumbing',
             'Nefco Corporation','Sparkleening', 'email_attachments', 'Positive Computer Services', 'Awisco']

PROCESSABLE_SUPPLIERS = ['BMW Plumbing Supplies', 'World Wide Plumbing', 'Y & S Plumbing Supply',
                         'Supreme Plumbing Supply','Pyramid Plumbing', 'ABC Opus Services', 'Park Plumbing Supply', 'Gotham Plumbing Supply']
