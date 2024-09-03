from fastapi import FastAPI
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from fastapi_pagination import add_pagination
from fastapi.middleware.cors import CORSMiddleware


from mpi_backend.api.routes import health
from mpi_backend.api.routes import supplier
from mpi_backend.api.routes import invoices_list
from mpi_backend.api.routes import get_mappings
from mpi_backend.api.routes import invoice_items
from mpi_backend.api.routes import quickbooks
from mpi_backend.api.routes import signin
from mpi_backend.api.routes import filters
from mpi_backend.config import LOG_LEVEL
from mpi_backend.utils.invoice_downloader import email_download_background_task
from mpi_backend.utils.invoice_convertor import convert_invoice
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.database import Base, engine
from mpi_backend.config.logging_config import setup_logging

# Base.metadata.create_all(engine)  # create db tables
setup_logging()

import logging
logger = logging.getLogger(__name__)
from middleware import MwTracker
tracker=MwTracker() # initializing middleware monitoring tool // comment out when running in local environment

@asynccontextmanager
async def lifespan(app:FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(email_download_background_task, "interval", minutes=3, max_instances=20)
    scheduler.start()
    yield

app = FastAPI(lifespan=lifespan)

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def register_routes(app):
    app.include_router(health.router)
    app.include_router(supplier.router)
    app.include_router(invoices_list.router)
    app.include_router(get_mappings.router)
    app.include_router(signin.router)
    app.include_router(invoice_items.router)
    app.include_router(quickbooks.router)
    app.include_router(filters.router)


register_routes(app)
add_pagination(app)
