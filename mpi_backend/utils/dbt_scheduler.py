"""
DBT Runner Module

Thread-safe dbt runner for executing materialized view refreshes.
Designed to be scheduled by the main APScheduler in scheduler.py.

TODO: Using APScheduler for now but we should consider using crontab if we move to a Linux-based deployment
or an orchestrator (even better)
"""

import os
import subprocess
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime
from enum import Enum
from uuid import UUID

from mpi_backend.database import SessionLocal
from mpi_backend.database.controllers.DbtRunController import DbtRunController
from mpi_backend.database.models.DbtRun import DbtRunStatus, DbtRunType
from mpi_backend.utils.elementary_report_service import generate_and_upload_report

logger = logging.getLogger(__name__)


class RefreshStatus(str, Enum):
    """Enum for refresh operation status."""
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"
    ALREADY_RUNNING = "already_running"
    STARTED = "started"


@dataclass
class RefreshResult:
    """Result of a refresh operation - typed contract between scheduler and router."""
    status: RefreshStatus
    execution_time: Optional[float] = None
    timestamp: Optional[datetime] = None
    error: Optional[str] = None
    output: Optional[str] = None
    data_load_status: Optional[str] = None
    data_load_error: Optional[str] = None
    message: Optional[str] = None


@dataclass
class DBTConfig:
    """Configuration for DBT runner from environment variables."""

    enabled: bool
    refresh_interval_minutes: int
    initial_delay_seconds: int
    timeout_seconds: int
    threads: int
    data_load_timeout_seconds: int
    test_enabled: bool

    @classmethod
    def from_env(cls) -> "DBTConfig":
        """
        Create configuration from environment variables.

        Environment Variables:
            DBT_SCHEDULER_ENABLED: Enable/disable DBT scheduling (default: true)
            DBT_REFRESH_INTERVAL_MINUTES: Refresh interval in minutes (default: 30)
            DBT_INITIAL_DELAY_SECONDS: Initial delay before first run (default: 30)
            DBT_TIMEOUT_SECONDS: Timeout for DBT operations (default: 1200)
            DBT_THREADS: Number of threads for dbt to use (default: 2)
            DATA_LOAD_TIMEOUT_SECONDS: Timeout for data loading step (default: 120)
            DBT_TEST_ENABLED: Enable dbt test step before Elementary report (default: true)

        Returns:
            DBTConfig instance with values from environment
        """
        return cls(
            enabled=os.getenv("DBT_SCHEDULER_ENABLED", "true").lower() == "true",
            refresh_interval_minutes=int(os.getenv("DBT_REFRESH_INTERVAL_MINUTES", "30")),
            initial_delay_seconds=int(os.getenv("DBT_INITIAL_DELAY_SECONDS", "30")),
            timeout_seconds=int(os.getenv("DBT_TIMEOUT_SECONDS", "1200")),
            threads=int(os.getenv("DBT_THREADS", "2")),
            data_load_timeout_seconds=int(os.getenv("DATA_LOAD_TIMEOUT_SECONDS", "240")),
            test_enabled=os.getenv("DBT_TEST_ENABLED", "true").lower() == "true",
        )


class DBTRunner:
    """
    Thread-safe dbt runner for executing materialized view refreshes.

    This class does NOT manage its own scheduler. Instead, it is designed
    to be called by the main APScheduler in scheduler.py.

    Features:
    - Thread-safe execution with RLock
    - Non-blocking try_refresh_materialized_views() method
    - Status tracking and monitoring
    - Manual refresh capability
    """

    def __init__(self, dbt_project_dir: Optional[str] = None, config: Optional[DBTConfig] = None):
        """
        Initialize the DBT runner.

        Args:
            dbt_project_dir: Path to dbt project directory (default: mpi_analytics)
            config: DBTConfig instance (default: load from environment)
        """
        self.config = config or DBTConfig.from_env()
        self._lock = threading.RLock()
        self._is_running = False

        # Set backend directory (parent of mpi_backend)
        self.backend_dir = Path(__file__).resolve().parent.parent.parent

        # Set dbt project directory
        if dbt_project_dir is None:
            # Default to mpi_analytics directory
            self.dbt_project_dir = self.backend_dir / "mpi_analytics"
        else:
            self.dbt_project_dir = Path(dbt_project_dir)

        # Verify dbt project exists
        if not self.dbt_project_dir.exists():
            logger.error(f"DBT project directory not found: {self.dbt_project_dir}")
            raise FileNotFoundError(f"DBT project not found: {self.dbt_project_dir}")

        # Track data load status (still kept in memory for now)
        self.last_data_load_status: str = "not_started"
        self.last_data_load_error: Optional[str] = None

        # Progress tracking
        self._current_step = 0
        self._total_steps = 0
        self._current_operation = "Idle"

        logger.info(f"DBT Runner initialized with backend dir: {self.backend_dir}, project dir: {self.dbt_project_dir}")

    def is_refresh_in_progress(self) -> bool:
        """
        Check if a refresh is currently in progress.

        Returns:
            True if refresh is running, False otherwise
        """
        with self._lock:
            return self._is_running

    def _run_subprocess(self, command: list, cwd: Path, timeout: int) -> tuple[str, Optional[str], Optional[str]]:
        """
        Run a subprocess and return (status, stdout, stderr).
        Status is one of: "success", "failed", "timeout", "error"
        """
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=str(cwd))
            if result.returncode == 0:
                return ("success", result.stdout, None)
            return ("failed", result.stdout, result.stderr)
        except subprocess.TimeoutExpired:
            return ("timeout", None, f"Timed out after {timeout} seconds")
        except Exception as e:
            return ("error", None, str(e))

    def _run_data_load(self) -> None:
        """Run data load scripts. Updates status but doesn't block on failure."""

        # Script 1: Load Google sheet mappings
        self._current_step = 1
        self._current_operation = "Loading Google Sheet Mappings"
        logger.info("Running Google sheet mappings load...")
        script_path = str(self.backend_dir / "scripts" / "load_raw_google_sheet_mappings.py")
        command = ["uv", "run", "python", script_path]

        status, stdout, stderr = self._run_subprocess(
            command,
            cwd=self.backend_dir,
            timeout=self.config.data_load_timeout_seconds
        )

        if status == "success":
            logger.info("Google sheet mappings load completed successfully")
        else:
            logger.error(f"Google sheet mappings load {status}: {stderr}")
            if stdout:
                logger.error(f"Google sheet mappings load output:\n{stdout}")

        # Script 2: Parse customer job addresses
        self._current_step = 2
        self._current_operation = "Parsing Customer Job Addresses"
        logger.info("Running customer job address parsing...")
        script_path = str(self.backend_dir / "scripts" / "parse_customer_job_addresses.py")
        command = ["uv", "run", "python", script_path]

        status2, stdout2, stderr2 = self._run_subprocess(
            command,
            cwd=self.backend_dir,
            timeout=self.config.data_load_timeout_seconds
        )

        if status2 == "success":
            logger.info("Customer job address parsing completed successfully")
        else:
            logger.error(f"Customer job address parsing {status2}: {stderr2}")
            if stdout2:
                logger.error(f"Customer job address parsing output:\n{stdout2}")

        # Update overall data load status (report worst status)
        final_status = status if status != "success" else status2
        final_error = stderr if status != "success" else stderr2
        self.last_data_load_status = final_status
        self.last_data_load_error = final_error

    def _run_dbt_snapshots(self) -> None:
        """Run dbt snapshots. Updates status but doesn't block on failure."""
        logger.info("Running dbt snapshots...")

        snapshot_models = ["snp__google_sheet_mappings"]

        command = [
            "uv", "run", "python", "run_dbt.py", "snapshot",
            "--select", " ".join(snapshot_models),
        ]

        logger.info(f"Running snapshots: {' '.join(command)} (cwd: {self.dbt_project_dir})")

        status, stdout, stderr = self._run_subprocess(
            command,
            cwd=self.dbt_project_dir,
            timeout=self.config.timeout_seconds
        )

        if status == "success":
            logger.info("DBT snapshots completed successfully")
        else:
            logger.error(f"DBT snapshots {status}: {stderr}")
            if stdout:
                logger.error(f"DBT snapshots output:\n{stdout}")

    def _run_dbt(self, start_time: datetime, full_refresh: bool = False, models: Optional[list] = None) -> RefreshResult:
        """Run dbt and return the result."""
        self._current_step = 3
        self._current_operation = "Running DBT Analytics"
        model_str = f"for models: {', '.join(models)}" if models else ""
        logger.info(f"Running dbt {'(full-refresh)' if full_refresh else ''} {model_str}")
        command = [
            "uv", "run", "python", "run_dbt.py", "run",
            "--threads", str(self.config.threads),
            "--exclude", "elementary",
        ]

        if full_refresh:
            command.append("--full-refresh")

        if models:
            command.extend(["--select"] + models)
        logger.info(f"Running models: {' '.join(command)} (cwd: {self.dbt_project_dir})")

        status, stdout, stderr = self._run_subprocess(
            command,
            cwd=self.dbt_project_dir,
            timeout=self.config.timeout_seconds
        )

        execution_time = (datetime.now() - start_time).total_seconds()

        if status == "success":
            logger.info(f"Refresh completed in {execution_time:.2f}s.")
            logger.info(f"DBT output: {stdout}")
        else:
            logger.error(f"DBT refresh {status} after {execution_time:.2f}s: {stderr}")
            if stdout:
                logger.error(f"DBT output:\n{stdout}")

        return RefreshResult(
            status=RefreshStatus(status),
            execution_time=execution_time,
            timestamp=datetime.now(),
            error=stderr,
            output=stdout,
            data_load_status=self.last_data_load_status,
            data_load_error=self.last_data_load_error
        )

    def _run_dbt_test(self) -> None:
        """Run dbt tests so Elementary has fresh test results for its report.

        Test failures are expected and intentionally non-blocking — failed tests
        are exactly what should appear in the Elementary report.
        """
        logger.info("Running dbt tests...")

        command = [
            "uv", "run", "python", "run_dbt.py", "test",
            "--threads", str(self.config.threads),
        ]

        logger.info(f"Running tests: {' '.join(command)} (cwd: {self.dbt_project_dir})")

        status, stdout, stderr = self._run_subprocess(
            command,
            cwd=self.dbt_project_dir,
            timeout=self.config.timeout_seconds
        )

        if status == "success":
            logger.info("DBT tests completed successfully (all tests passed)")
        elif status == "failed":
            logger.warning("DBT tests failed — non-blocking so failures appear in the Elementary report")
            if stderr:
                logger.warning(f"DBT test stderr:\n{stderr}")
            if stdout:
                logger.info(f"DBT test output:\n{stdout}")
        else:
            # "timeout" or "error" are operational issues, not test assertion failures
            logger.error(f"DBT test execution issue (status='{status}') — continuing non-blocking")
            if stderr:
                logger.error(f"DBT test stderr:\n{stderr}")
            if stdout:
                logger.warning(f"DBT test output:\n{stdout}")

    def try_refresh_materialized_views(self, user_id: Optional[UUID] = None, full_refresh: bool = False, models: Optional[list] = None) -> RefreshResult:
        """
        Try to refresh materialized views. Returns immediately if already running.

        This is a non-blocking method that will not wait if a refresh is already
        in progress. Runs data load script, dbt snapshots, then dbt models with thread safety.

        Returns:
            RefreshResult with result or status indicating refresh is already running
        """
        # First check if a process is already running and exit early
        with self._lock:
            if self._is_running:
                return RefreshResult(
                    status=RefreshStatus.ALREADY_RUNNING,
                    message="A refresh is already in progress"
                )
            self._is_running = True
            # Base: data load + snapshots + dbt run + report + complete.
            # Data load + snapshots are skipped when `models` is explicitly passed.
            # dbt test is skipped when DBT_TEST_ENABLED=false.
            base_steps = 3 if models else 5
            self._total_steps = base_steps + (1 if self.config.test_enabled else 0)
            self._current_step = 0
            self._current_operation = "Initializing"

        run_log = None
        db = None
        try:
            db = SessionLocal()
            controller = DbtRunController(db)
            run_type = DbtRunType.FULL_REFRESH if full_refresh else DbtRunType.REGULAR
            run_log = controller.create_run_log(run_type=run_type, triggered_by=user_id)

            start_time = datetime.now()
            final_status = None
            final_error = None
            execution_time = None

            try:
                if not models:
                    # Step 1: Data load
                    self._run_data_load()

                    # Step 2: DBT Snapshots (Capture history from newly loaded data)
                    self._run_dbt_snapshots()

                # Step 3: DBT run (Refresh models/marts)
                result = self._run_dbt(start_time, full_refresh=full_refresh, models=models)
                final_status = DbtRunStatus(result.status.value)
                final_error = result.error
                execution_time = result.execution_time

                logger.info(f"DBT run with {run_type} finished in: {execution_time}")

                # dbt test (feeds Elementary report with fresh test results)
                if result.status == RefreshStatus.SUCCESS and self.config.test_enabled:
                    self._current_step += 1
                    self._current_operation = "Running DBT Tests"
                    self._run_dbt_test()

                # Generate Elementary report (non-blocking, best-effort)
                if result.status == RefreshStatus.SUCCESS:
                    self._current_step += 1
                    self._current_operation = "Generating Elementary Report"
                    logger.info(self._current_operation)
                    try:
                        s3_key = generate_and_upload_report()
                        if s3_key:
                            logger.info(f"Elementary report uploaded: {s3_key}")
                    except Exception as report_err:
                        logger.exception(f"Elementary report generation failed (non-fatal): {report_err}")

                self._current_step = self._total_steps
                self._current_operation = "Complete"
                logger.info(self._current_operation)
                return result
            except Exception as e:
                final_status = DbtRunStatus.ERROR
                final_error = str(e)
                execution_time = (datetime.now() - start_time).total_seconds()
                logger.exception(f"Unexpected error in try_refresh_materialized_views: {e}")
                raise
            finally:
                if run_log is not None:
                    try:
                        controller.update_run_log(
                            run_id=run_log.id,
                            status=final_status if final_status else DbtRunStatus.ERROR,
                            error_message=final_error,
                            execution_time=execution_time
                        )
                    except Exception as log_err:
                        logger.error(f"Failed to update run log {run_log.id}: {log_err}")
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception as e:
                    logger.warning(f"Error closing DB session: {e}")
            with self._lock:
                logger.info("Setting _is_running to false since the refresh is done")
                self._is_running = False
                self._current_step = 0
                self._total_steps = 0
                self._current_operation = "Idle"

    def get_status(self) -> Dict:
        """
        Get current runner status and health information.

        Returns:
            Dict with runner status, last refresh info, and health metrics
        """
        db = SessionLocal()
        controller = DbtRunController(db)
        try:
            last_run = controller.get_latest_run()
            last_status = last_run.status if last_run else "not_started"
            last_time = last_run.started_at.isoformat() if last_run and last_run.started_at else None
            last_error = last_run.error_message if last_run else None
            total_refreshes = controller.get_success_count()

            with self._lock:
                is_running = self._is_running
        finally:
            db.close()

        with self._lock:
            return {
                "is_running": is_running,
                "current_step": self._current_step,
                "total_steps": self._total_steps,
                "current_operation": self._current_operation,
                "last_refresh_time": last_time,
                "last_refresh_status": last_status,
                "last_refresh_error": last_error,
                "last_data_load_status": self.last_data_load_status,
                "last_data_load_error": self.last_data_load_error,
                "total_refreshes": total_refreshes,
                "config": {
                    "enabled": self.config.enabled,
                    "refresh_interval_minutes": self.config.refresh_interval_minutes,
                    "initial_delay_seconds": self.config.initial_delay_seconds,
                    "timeout_seconds": self.config.timeout_seconds,
                    "threads": self.config.threads,
                    "data_load_timeout_seconds": self.config.data_load_timeout_seconds,
                    "test_enabled": self.config.test_enabled,
                }
            }


# Global runner instance (singleton pattern)
_dbt_runner_instance: Optional[DBTRunner] = None
_dbt_runner_lock = threading.Lock()


def get_dbt_runner() -> DBTRunner:
    """
    Get or create the global DBT runner instance.

    Returns:
        DBTRunner instance
    """
    global _dbt_runner_instance
    with _dbt_runner_lock:
        if _dbt_runner_instance is None:
            _dbt_runner_instance = DBTRunner()
        return _dbt_runner_instance
