import logging
from fastapi import FastAPI

from mpi_backend.api.routes import health
from mpi_backend.config import LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

app = FastAPI()


def register_routes(app):
    app.include_router(health.router)


register_routes(app)
