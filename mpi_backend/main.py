import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from mpi_backend.api.routes import health
from mpi_backend.config import LOG_LEVEL
from mpi_backend.utils.invoice_downloader import email_download_background_task
from mpi_backend.utils.invoice_convertor import convert_invoice
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.database import Base, engine

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)
Base.metadata.create_all(engine)  # create db tables


@asynccontextmanager
async def lifespan(app:FastAPI):
    scheduler = BackgroundScheduler()
    # scheduler.add_job(email_download_background_task, "interval", minutes=0.1, max_instances=1)
    scheduler.add_job(convert_invoice, "interval", minutes=0.2, max_instances=1, id="convert_invoice_job")
    scheduler.add_listener(process_extracted_data, EVENT_JOB_EXECUTED)
    scheduler.start()
    yield

app = FastAPI(lifespan=lifespan)


def register_routes(app):
    app.include_router(health.router)


register_routes(app)
