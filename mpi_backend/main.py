from fastapi import FastAPI
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from fastapi_pagination import add_pagination
from fastapi.middleware.cors import CORSMiddleware
import pytz
from datetime import datetime
# from apitally.fastapi import ApitallyMiddleware


from mpi_backend.api.routes import health
from mpi_backend.api.routes import supplier
from mpi_backend.api.routes import invoices_list
from mpi_backend.api.routes import get_mappings
from mpi_backend.api.routes import invoice_items
from mpi_backend.api.routes import quickbooks
from mpi_backend.api.routes import signin
from mpi_backend.api.routes import filters
from mpi_backend.api.routes import sync_mappings
from mpi_backend.api.routes import price_comparison
from mpi_backend.api.routes.sync_mappings import perform_sync_mapping_task, perform_update_all_mappings
from mpi_backend.config import LOG_LEVEL
from mpi_backend.utils.invoice_downaloder import email_download_background_task
from mpi_backend.utils.missing_invoice_downaloder import missing_email_download_background_task

from mpi_backend.utils.invoice_convertor import convert_invoice
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.database import Base, engine
from mpi_backend.config.logging_config import setup_logging

# Base.metadata.create_all(engine)  # create db tables
setup_logging()

import logging

logger = logging.getLogger(__name__)

# from middleware import MwTracker
# tracker=MwTracker() # initializing middleware monitoring tool // comment out when running in local environment

UTC_TZ = pytz.utc  # UTC Time Zone


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(email_download_background_task, "interval", minutes=3, max_instances=20)

    # Run the sync_mappings job on a 30-minute interval
    scheduler.add_job(
        perform_sync_mapping_task,
        "interval",
        minutes=30,
        replace_existing=True,
        max_instances=1
    )

    # Run the update_all_mappings job every 24 hours
    scheduler.add_job(
        perform_update_all_mappings,
        CronTrigger(hour=3, minute=0, timezone=UTC_TZ),  # Run at 3 AM UTC
        id="update_all_mappings_daily",
        replace_existing=True,
        max_instances=1
    )

    # # Also run the sync_mappings job immediately on startup
    # scheduler.add_job(
    #     perform_sync_mapping_task,
    #     DateTrigger(run_date=datetime.now()),
    #     replace_existing=True,
    #     id="startup_sync_mappings"
    # )

    # scheduler.add_job(missing_email_download_background_task,
    #                   CronTrigger(hour=5, minute=0, timezone=UTC_TZ),
    #                   # Eastern Time: 9:00 PM Previous Day
    #                   # European Time: 3:00 AM Same Day
    #                   max_instances=1,
    #                   replace_existing=True  # Avoids duplicate jobs if restarted
    #                   )

    # Run the job only once when the application starts (non-blocking)
    #scheduler.add_job(
    #    missing_email_download_background_task,
    #    DateTrigger(run_date=datetime.now()),  # Runs once at startup
    #    replace_existing=True
    #)

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


# app.add_middleware(
#     ApitallyMiddleware,
#     client_id="d2f20325-2b6d-4fe0-8a73-a757ae4227b8",
#     env="prod",  # or "dev"
# )


def register_routes(app):
    app.include_router(health.router)
    app.include_router(supplier.router)
    app.include_router(invoices_list.router)
    app.include_router(get_mappings.router)
    app.include_router(signin.router)
    app.include_router(invoice_items.router)
    app.include_router(quickbooks.router)
    app.include_router(filters.router)
    app.include_router(sync_mappings.router)
    app.include_router(price_comparison.router)


register_routes(app)
add_pagination(app)
