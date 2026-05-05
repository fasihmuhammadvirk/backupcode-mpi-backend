"""
Elementary Report Service

Generates Elementary data observability reports and optionally uploads them
to S3 using the native `edr send-report` command.

Invoked via `uv run python run_edr.py` from the mpi_analytics directory,
matching the project's convention for `run_dbt.py`.
"""

import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from mpi_backend.config import (
    AWS_SERVER_PUBLIC_KEY,
    AWS_SERVER_SECRET_KEY,
    ELEMENTARY_S3_BUCKET_NAME,
    ELEMENTARY_S3_REGION,
    ELEMENTARY_REPORT_ENABLED,
    ENVIRONMENT,
)

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DBT_PROJECT_DIR = BACKEND_DIR / "mpi_analytics"
PROFILES_DIR = DBT_PROJECT_DIR

EDR_TIMEOUT_SECONDS = 600
DBT_PROFILE_TARGET = os.getenv("DBT_PROFILE_TARGET", "dev")


def _build_base_args() -> list[str]:
    """Common edr flags shared by both local and S3 report generation."""
    return [
        "--project-dir", str(DBT_PROJECT_DIR),
        "--profiles-dir", str(PROFILES_DIR),
        "--profile-target", DBT_PROFILE_TARGET,
    ]


def _run_edr(
    command_args: list[str],
    timeout: int = EDR_TIMEOUT_SECONDS,
    extra_env: Optional[dict[str, str]] = None,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Run an edr command via `uv run python run_edr.py`.

    Returns (status, stdout, stderr) matching DBTRunner._run_subprocess convention.
    """
    command = ["uv", "run", "python", "run_edr.py"] + command_args

    logger.info("Running Elementary: uv run python run_edr.py %s (cwd: %s)", " ".join(command_args), DBT_PROJECT_DIR)

    env = {**os.environ, **(extra_env or {})}

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(DBT_PROJECT_DIR),
            env=env,
        )
        if result.returncode == 0:
            return ("success", result.stdout, None)
        return ("failed", result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        return ("timeout", None, f"Timed out after {timeout} seconds")
    except Exception as e:
        return ("error", None, str(e))


def generate_local_report(file_path: Optional[str] = None) -> Optional[str]:
    """Generate an Elementary HTML report locally (no S3 upload).

    Useful for debugging or manual inspection.
    Returns the path to the generated HTML file, or None on failure.
    """
    if file_path is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_path = str(DBT_PROJECT_DIR / "target" / f"elementary_report_{timestamp}.html")

    args = ["report"] + _build_base_args() + ["--file-path", file_path]

    status, stdout, stderr = _run_edr(args)

    if status == "success":
        if Path(file_path).exists():
            logger.info("Elementary local report generated: %s", file_path)
            return file_path
        logger.warning("edr report succeeded but file not found at %s", file_path)
        logger.info("edr stdout: %s", stdout)
        return None

    logger.error("Elementary local report failed (%s)\nstdout: %s\nstderr: %s", status, stdout, stderr)
    return None


def send_report_to_s3() -> Optional[str]:
    """Generate an Elementary report and upload it to S3 using edr send-report.

    Uses the native `edr send-report` S3 flags so no separate boto3 upload is needed.
    Returns the S3 bucket file path on success, or None on failure.
    """
    if not ELEMENTARY_S3_BUCKET_NAME:
        logger.warning("ELEMENTARY_S3_BUCKET_NAME not configured; skipping S3 upload")
        return None

    if not AWS_SERVER_PUBLIC_KEY or not AWS_SERVER_SECRET_KEY:
        logger.warning("AWS credentials not configured (set PUBLIC_ACCESS_KEY and SECRET_ACCESS_KEY in .env); skipping S3 upload")
        return None

    bucket_file_path = "elementary_report.html"

    args = [
        "send-report",
        *_build_base_args(),
        "--s3-bucket-name", ELEMENTARY_S3_BUCKET_NAME,
        "--aws-region-name", ELEMENTARY_S3_REGION,
        "--bucket-file-path", bucket_file_path,
    ]

    status, stdout, stderr = _run_edr(args, extra_env={
        "AWS_ACCESS_KEY_ID": AWS_SERVER_PUBLIC_KEY,
        "AWS_SECRET_ACCESS_KEY": AWS_SERVER_SECRET_KEY,
    })

    if status == "success":
        logger.info(
            "Elementary report uploaded to s3://%s/%s",
            ELEMENTARY_S3_BUCKET_NAME,
            bucket_file_path,
        )
        return bucket_file_path

    logger.error("Elementary send-report failed (%s)\nstdout: %s\nstderr: %s", status, stdout, stderr)
    return None


def generate_and_upload_report() -> Optional[str]:
    """Entry point called after dbt runs.

    Gated by ELEMENTARY_REPORT_ENABLED and ENVIRONMENT=production.
    Returns the S3 key on success, or None.
    """
    if not ELEMENTARY_REPORT_ENABLED:
        logger.info("Elementary report generation is disabled (ELEMENTARY_REPORT_ENABLED=false)")
        return None

    if ENVIRONMENT != "production":
        logger.info("Elementary S3 upload skipped (ENVIRONMENT=%s, requires 'production')", ENVIRONMENT)
        return None

    return send_report_to_s3()
