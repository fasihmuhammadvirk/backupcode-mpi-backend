import os
from dotenv import load_dotenv
from pathlib import Path

dotenv_path = Path('mpi_backend/.env')
load_dotenv(dotenv_path=dotenv_path)

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
INVOICE_DOWNLOAD_FOLDER = os.getenv("INVOICE_DOWNLOAD_FOLDER")
