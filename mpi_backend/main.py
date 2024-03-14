import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler

from mpi_backend.api.routes import health
from mpi_backend.config import LOG_LEVEL
from mpi_backend.utils.invoice_downloader import email_download_background_task
from mpi_backend.utils.invoice_convertor import convert_invoice

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app:FastAPI):
    scheduler = BackgroundScheduler()
    # scheduler.add_job(email_download_background_task, "interval", minutes=0.1, max_instances=1)
    scheduler.add_job(convert_invoice, "interval", minutes=0.2, max_instances=1)
    scheduler.start()
    yield

app = FastAPI(lifespan=lifespan)


def register_routes(app):
    app.include_router(health.router)


register_routes(app)
