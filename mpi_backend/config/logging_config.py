import logging
import logging.config
import os

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s - %(levelname)s - %(message)s",
        },
        "detailed": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "level": "INFO",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/app.log",
            "formatter": "detailed",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "level": "INFO",
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/error.log",
            "formatter": "detailed",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "level": "ERROR",
        }
    },
    "root": {
        "handlers": ["console", "file", "error_file"],
        "level": "INFO",
    },
    "loggers": {
        "uvicorn": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["console", "error_file"],
            "level": "ERROR",
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "sqlalchemy.engine": {
            "handlers": ["file"],
            "level": "WARNING",  # Only log warnings and errors for SQL queries
            "propagate": False,
        },
        "mpi_backend.database.controllers": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "mpi_backend.api.routes": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        }
    },
}

def setup_logging():
    logging.config.dictConfig(LOGGING_CONFIG)
    logging.info("Logging configured successfully")
