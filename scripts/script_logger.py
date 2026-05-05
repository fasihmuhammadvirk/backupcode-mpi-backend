"""
Script Logger Utility for Grafana Alloy Integration

Provides a shared logging factory for scripts that:
- Uses the same format as the main app
- Writes to a configurable log path, which defaults to `logs/scripts/{parent_dir}_{script_name}.log`, but can be overridden via the environment variable `MPI_SCRIPTS_LOG_DIR`
- Fails loudly if file logging cannot be initialized (so issues are caught early)
- Labels separately from main app in Alloy (job="mpi-scripts")

Usage:
    from scripts.script_logger import get_script_logger
    logger = get_script_logger(__file__)
    logger.info("Script started")
"""

import logging
import sys
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os

from mpi_backend.config.logging_config import AsciiSafeFormatter


# Log format matching main app
LOG_FORMAT = "[%(asctime)s - %(name)s->%(funcName)s():%(lineno)s]%(levelname)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Script logs directory (absolute path relative to repo root), can be overridden
REPO_ROOT = Path(__file__).resolve().parent.parent
env_log_dir = os.getenv("MPI_SCRIPTS_LOG_DIR")
if env_log_dir:
    SCRIPTS_LOG_DIR = Path(env_log_dir)
else:
    SCRIPTS_LOG_DIR = REPO_ROOT / "logs" / "scripts"


def get_script_logger(script_path: str, level: int = logging.INFO) -> logging.Logger:
    """
    Get a logger configured for script execution.

    Args:
        script_path: Pass __file__ to automatically derive script name
        level: Logging level (default: INFO)

    Returns:
        Configured logger instance

    Example:
        logger = get_script_logger(__file__)
        logger.info("Processing started")
    """
    # Extract script name from path (e.g., "backup_database" from "/path/to/backup_database.py")
    # Use parent directory name to distinguish scripts with same name (e.g., "scripts_backup_database")
    path_obj = Path(script_path).resolve()
    script_name = f"{path_obj.parent.name}_{path_obj.stem}"

    # Create logs/scripts directory if needed
    SCRIPTS_LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Create logger with script name
    logger = logging.getLogger(f"script.{script_name}")

    # Always enforce level and propagate settings (idempotent)
    logger.setLevel(level)
    logger.propagate = False

    # Update existing handler levels
    for handler in logger.handlers:
        handler.setLevel(level)

    # Check which handler types already exist
    has_file_handler = any(isinstance(h, RotatingFileHandler) for h in logger.handlers)
    has_stream_handler = any(
        isinstance(h, logging.StreamHandler) and h.stream == sys.stdout
        for h in logger.handlers
    )

    # Only add handlers if they don't already exist
    if has_file_handler and has_stream_handler:
        return logger

    # Create formatter using the same AsciiSafeFormatter as main app
    formatter = AsciiSafeFormatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)

    # File handler - per-script log file with rotation
    if not has_file_handler:
        # Ensure the log directory exists
        SCRIPTS_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = SCRIPTS_LOG_DIR / f"{script_name}.log"
        file_handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Console handler
    if not has_stream_handler:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


@contextmanager
def timed(name: str, logger: logging.Logger | None = None):
    """
    Context manager that logs elapsed time for a code block.

    Args:
        name: Label for the timed operation (appears in log output)
        logger: Logger instance to use. If None, uses module logger.

    Usage:
        with timed("download_pdf", logger):
            download_file()

    Output:
        [TIMING] download_pdf: 1.23s
    """
    log = logger or logging.getLogger(__name__)
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        log.info(f"[TIMING] {name}: {elapsed:.2f}s")
