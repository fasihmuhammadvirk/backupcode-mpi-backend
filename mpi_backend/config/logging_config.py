import logging
import logging.config
import os

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

class AsciiSafeFormatter(logging.Formatter):
    """Formatter that strips non-ASCII characters after standard formatting."""

    def format(self, record: logging.LogRecord) -> str:
        # First perform standard formatting (which safely applies %s args)
        msg = super().format(record)
        try:
            return msg.encode("ascii", "ignore").decode("ascii")
        except Exception:
            return "Log message encoding error"


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "mpi_backend.config.logging_config.AsciiSafeFormatter",
            "format": "%(asctime)s - %(levelname)s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "detailed": {
            "()": "mpi_backend.config.logging_config.AsciiSafeFormatter",
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "level": "INFO",
            "stream": "ext://sys.stdout"
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/app.log",
            "formatter": "detailed",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "level": "INFO",
            "encoding": "utf-8"
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/error.log",
            "formatter": "detailed",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "level": "ERROR",
            "encoding": "utf-8"
        },
        "missing_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/missing.log",
            "formatter": "detailed",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "level": "INFO",
            "encoding": "utf-8"
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
            "handlers": ["file"],
            "level": "WARNING",
            "propagate": False,
        },
        "sqlalchemy.engine": {
            "handlers": ["file"],
            "level": "WARNING",
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
        },
        # Quiet noisy third‑party libs on Windows
        "camelot": {
            "handlers": ["file"],
            "level": "WARNING",
            "propagate": False,
        },
        "pdfminer": {
            "handlers": ["file"],
            "level": "WARNING",
            "propagate": False,
        },
        "matplotlib": {
            "handlers": ["file"],
            "level": "WARNING",
            "propagate": False,
        },
        "missing_logger": {
            "handlers": ["missing_file"],
            "level": "INFO",
            "propagate": False,
        }
    },
}

def setup_logging():
    logging.config.dictConfig(LOGGING_CONFIG)
    logging.info("Logging configured successfully - ASCII mode enabled")

def get_missing_logger():
    """Get a logger specifically for missing items/emails/attachments"""
    return logging.getLogger("missing_logger")
