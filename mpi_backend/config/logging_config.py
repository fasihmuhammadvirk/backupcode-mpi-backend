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
            "datefmt": "%Y-%m-%d %H:%M:%S"
        },
        "detailed": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S"
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
            "level": "WARNING",  # Reduce uvicorn access log noise
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
        }
    },
}

def setup_logging():
    logging.config.dictConfig(LOGGING_CONFIG)
    
    # Ensure all log messages are ASCII-safe
    class ASCIIFilter(logging.Filter):
        def filter(self, record):
            # Convert message to ASCII-safe string, removing any special characters
            if hasattr(record, 'msg'):
                try:
                    # Convert to string and encode/decode to remove non-ASCII chars
                    record.msg = str(record.msg).encode('ascii', 'ignore').decode('ascii')
                except:
                    record.msg = "Log message encoding error"
            return True
    
    # Add ASCII filter to all handlers
    for handler in logging.getLogger().handlers:
        handler.addFilter(ASCIIFilter())
    
    logging.info("Logging configured successfully - ASCII mode enabled")
