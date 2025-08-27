from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from mpi_backend.database import get_db, get_db_health_status
from mpi_backend.background.scheduler import (
    get_system_metrics, resource_monitor
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Basic health check endpoint"""
    try:
        # Simple health check without HealthController
        return {"status": "healthy", "message": "MPI Backend is running"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


@router.get("/health/db-pool")
async def database_pool_health():
    """Database connection pool health check"""
    try:
        pool_status = get_db_health_status()
        return {
            "status": "healthy" if pool_status["healthy"] else "warning",
            "database_pools": pool_status,
            "message": "Database pool status retrieved successfully"
        }
    except Exception as e:
        logger.error(f"Database pool health check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "message": "Failed to retrieve database pool status"
        }


@router.get("/health/system")
async def system_health():
    """Detailed system health and resource monitoring"""
    try:
        metrics = get_system_metrics()
        return {
            "status": "success",
            "data": metrics
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to get system metrics: {str(e)}"
        )


@router.get("/health/jobs")
async def jobs_health():
    """Background jobs health and status"""
    try:
        # Get active jobs
        active_jobs = [
            {
                "job_id": job_id,
                "start_time": metrics.start_time.isoformat(),
                "duration": metrics.duration,
                "success": metrics.success,
                "error_count": metrics.error_count,
                "last_error": metrics.last_error,
                "system_load_before": metrics.system_load_before,
                "system_load_after": metrics.system_load_after
            }
            for job_id, metrics in resource_monitor.metrics.items()
            if not metrics.end_time  # Active jobs
        ]
        
        # Get circuit breaker status
        circuit_breaker = resource_monitor.circuit_breaker
        
        # Get recent job history (last 24 hours)
        from datetime import datetime, timedelta
        cutoff_time = datetime.now() - timedelta(hours=24)
        recent_jobs = [
            {
                "job_id": job_id,
                "start_time": metrics.start_time.isoformat(),
                "end_time": metrics.end_time.isoformat() if metrics.end_time else None,
                "duration": metrics.duration,
                "success": metrics.success,
                "error_count": metrics.error_count
            }
            for job_id, metrics in resource_monitor.metrics.items()
            if metrics.start_time > cutoff_time
        ]
        
        return {
            "status": "success",
            "data": {
                "active_jobs": active_jobs,
                "circuit_breaker": circuit_breaker,
                "recent_jobs": recent_jobs,
                "total_jobs_today": len([
                    m for m in resource_monitor.metrics.values() 
                    if m.start_time.date() == datetime.now().date()
                ])
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to get jobs health: {str(e)}"
        )


@router.post("/health/jobs/{job_id}/reset")
async def reset_job_circuit_breaker(job_id: str):
    """Reset circuit breaker for a specific job"""
    try:
        if job_id in resource_monitor.circuit_breaker:
            del resource_monitor.circuit_breaker[job_id]
            return {
                "status": "success",
                "message": f"Circuit breaker reset for job {job_id}"
            }
        else:
            return {
                "status": "success",
                "message": f"Job {job_id} has no circuit breaker to reset"
            }
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to reset circuit breaker: {str(e)}"
        )
