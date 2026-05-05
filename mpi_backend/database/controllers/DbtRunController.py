import logging
from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID

from sqlalchemy.orm import Session
from mpi_backend.database.models.DbtRun import DbtRunLog, DbtRunStatus, DbtRunType

logger = logging.getLogger(__name__)

class DbtRunController:
    def __init__(self, db: Session):
        self.db = db

    def create_run_log(
        self,
        run_type: DbtRunType = DbtRunType.REGULAR,
        triggered_by: Optional[UUID] = None
    ) -> DbtRunLog:
        """
        Create a new DBT run log entry.
        """
        try:
            run_log = DbtRunLog(
                status=DbtRunStatus.RUNNING.value,
                run_type=run_type.value,
                triggered_by=triggered_by
            )
            self.db.add(run_log)
            self.db.commit()
            self.db.refresh(run_log)
            return run_log
        except Exception:
            self.db.rollback()
            logger.exception("Error creating DBT run log")
            raise

    def update_run_log(
        self,
        run_id: int,
        status: DbtRunStatus,
        error_message: Optional[str] = None,
        execution_time: Optional[float] = None
    ) -> DbtRunLog:
        """
        Update an existing DBT run log entry.
        """
        try:
            run_log = self.db.query(DbtRunLog).filter(DbtRunLog.id == run_id).first()
            if not run_log:
                raise ValueError(f"DBT run log entry with id: {run_id} not found")
            run_log.status = status.value
            run_log.error_message = error_message
            run_log.execution_time = execution_time
            run_log.ended_at = datetime.now(tz=timezone.utc)
            self.db.commit()
            self.db.refresh(run_log)
            return run_log
        except ValueError:
            self.db.rollback()
            logger.exception("Error updating DBT run log")
            raise
        except Exception:
            self.db.rollback()
            logger.exception(f"Error updating DBT run log {run_id}")
            raise

    def get_latest_run(self) -> Optional[DbtRunLog]:
        """
        Get the most recent DBT run log.
        """
        return self.db.query(DbtRunLog).order_by(DbtRunLog.id.desc()).first()

    def get_run_history(self, limit: int = 10) -> List[DbtRunLog]:
        """
        Get the history of recent DBT runs.
        """
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        return self.db.query(DbtRunLog).order_by(DbtRunLog.id.desc()).limit(limit).all()

    def get_success_count(self) -> int:
        """
        Get the total count of successful DBT runs.
        """
        return self.db.query(DbtRunLog).filter(DbtRunLog.status == DbtRunStatus.SUCCESS.value).count()
