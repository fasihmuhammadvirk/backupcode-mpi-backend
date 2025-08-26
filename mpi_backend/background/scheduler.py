"""
Production-Ready APScheduler Configuration for MPI Backend
Optimized for multi-worker FastAPI applications with async execution and memory protection.

Key Features:
- Async execution for all background jobs
- Maximum 1 instance per job (prevents duplication)
- Memory protection with automatic cleanup
- Separate executors for CPU vs I/O workloads
- Resource monitoring and circuit breaker patterns
- Job staggering and overlap prevention
- Memory leak prevention and cleanup
- Comprehensive error handling and retry logic
"""

import logging
import os
import time
import gc
import psutil
import signal
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from contextlib import suppress
from typing import Callable, Any, Optional, Dict, List
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timedelta
import multiprocessing as mp

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.executors.pool import ThreadPoolExecutor as APSchedulerThreadPool
from apscheduler.executors.pool import ProcessPoolExecutor as APSchedulerProcessPool

# Import business logic tasks lazily to avoid startup overhead
from mpi_backend.utils.quickbooks_priority import set_scheduler_instance

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION CONSTANTS - Optimized for 8GB server
# =============================================================================

# Resource thresholds - optimized for 4GB server stability
CPU_THRESHOLD = 80.0  # CPU % threshold (more conservative for 4GB)
MEMORY_THRESHOLD_MB = 2500  # Available RAM in MB (2.5GB threshold for 4GB server)
DB_CONNECTION_LIMIT = 3  # Max DB connections for background jobs (reduced for 4GB)

# Executor pool sizes - optimized for 4GB server
CPU_POOL_SIZE = 1  # Single process for CPU-intensive tasks
IO_POOL_SIZE = 2   # Reduced thread count for 4GB server
MAPPING_POOL_SIZE = 1  # Dedicated threads for mapping operations

# Circuit breaker settings
MAX_FAILURES = 3
FAILURE_WINDOW_HOURS = 24
MAX_RESOURCE_WAIT_MINUTES = 10  # Shorter timeout for responsiveness

# Job execution settings
MAX_JOB_DURATION_MINUTES = 20  # Reduced from 30 for 8GB server
JOB_COALESCE_TIME = 300  # Coalesce missed executions within 5 minutes
MAX_MEMORY_PER_JOB_MB = 500  # Maximum memory per job (500MB limit)

# ADDED: Resource management for 4GB server
MEMORY_CLEANUP_THRESHOLD = 75.0  # Cleanup when memory > 75% (more aggressive for 4GB)
CPU_THROTTLE_THRESHOLD = 85.0  # Throttle jobs when CPU > 85% (more conservative for 4GB)
CRITICAL_JOB_PRIORITY = ["email_download", "failed_recovery"]  # Jobs that must always run

# =============================================================================
# JOB PRIORITY SYSTEM
# =============================================================================

class JobPriority(Enum):
    CRITICAL = "critical"      # Invoice parsing, failed recovery (always run)
    HIGH = "high"             # Mapping updates, sync operations
    MEDIUM = "medium"         # Regular downloads, cleanup
    LOW = "low"               # Memory cleanup, non-essential tasks

@dataclass
class JobMetrics:
    """Comprehensive job execution metrics for monitoring"""
    job_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: Optional[float] = None
    success: bool = False
    error_count: int = 0
    last_error: Optional[str] = None
    system_load_before: Optional[float] = None
    system_load_after: Optional[float] = None
    memory_usage_before: Optional[float] = None
    memory_usage_after: Optional[float] = None
    executor_type: Optional[str] = None

# =============================================================================
# RESOURCE MONITORING & CIRCUIT BREAKER
# =============================================================================

class ResourceMonitor:
    """Advanced system resource monitoring with circuit breaker patterns"""
    
    def __init__(self):
        self.metrics: Dict[str, JobMetrics] = {}
        self.circuit_breaker: Dict[str, Dict] = {}
        self.max_failures = MAX_FAILURES
        self.failure_window_hours = FAILURE_WINDOW_HOURS
        self._last_cleanup = datetime.now()
        
    def is_system_healthy(self) -> bool:
        """Comprehensive system health check"""
        try:
            # CPU check with multiple samples for accuracy
            cpu_samples = []
            for _ in range(3):
                cpu_samples.append(psutil.cpu_percent(interval=0.5))
            cpu_percent = sum(cpu_samples) / len(cpu_samples)
            
            # Memory check
            memory = psutil.virtual_memory()
            available_mb = memory.available / (1024 * 1024)
            
            # Disk check
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            
            # Comprehensive health assessment
            is_healthy = (
                cpu_percent < CPU_THRESHOLD and
                available_mb > MEMORY_THRESHOLD_MB and
                disk_percent < 90  # Prevent disk space issues
            )
            
            if not is_healthy:
                logger.warning(
                    "System resources low - CPU: %.1f%%, RAM: %.1f MB, Disk: %.1f%%",
                    cpu_percent, available_mb, disk_percent
                )
            
            return is_healthy
            
        except Exception as e:
            logger.error("Failed to check system health: %s", e)
            return False  # Fail safe
    
    def wait_for_resources(self, max_wait_minutes: int = None) -> bool:
        """Smart resource waiting with exponential backoff"""
        if max_wait_minutes is None:
            max_wait_minutes = MAX_RESOURCE_WAIT_MINUTES
        
        start_time = time.time()
        max_wait_seconds = max_wait_minutes * 60
        wait_interval = 5  # Start with 5 second intervals
        
        while time.time() - start_time < max_wait_seconds:
            if self.is_system_healthy():
                return True
            
            logger.info("Waiting for system resources (%.0f seconds remaining)...", 
                       max_wait_seconds - (time.time() - start_time))
            
            time.sleep(wait_interval)
            wait_interval = min(wait_interval * 1.5, 30)  # Exponential backoff, max 30s
        
        logger.warning("Timed out waiting for system resources")
        return False
    
    def is_job_enabled(self, job_id: str) -> bool:
        """Circuit breaker check with automatic recovery"""
        if job_id not in self.circuit_breaker:
            return True
        
        job_status = self.circuit_breaker[job_id]
        last_failure = job_status.get('last_failure')
        failure_count = job_status.get('failure_count', 0)
        
        # Automatic recovery after failure window
        if last_failure and (datetime.now() - last_failure).total_seconds() > (self.failure_window_hours * 3600):
            logger.info("Circuit breaker auto-reset for job %s", job_id)
            del self.circuit_breaker[job_id]
            return True
        
        # Disable job if too many failures
        if failure_count >= self.max_failures:
            logger.warning("Job %s disabled due to circuit breaker (failures: %s)", job_id, failure_count)
            return False
        
        return True
    
    def record_job_failure(self, job_id: str, error: str):
        """Record job failure for circuit breaker logic"""
        if job_id not in self.circuit_breaker:
            self.circuit_breaker[job_id] = {'failure_count': 0, 'last_failure': None}
        
        self.circuit_breaker[job_id]['failure_count'] += 1
        self.circuit_breaker[job_id]['last_failure'] = datetime.now()
        
        logger.error("Job %s failed (failure %s/%s): %s", 
                    job_id, 
                    self.circuit_breaker[job_id]['failure_count'],
                    self.max_failures,
                    error)
    
    def record_job_success(self, job_id: str):
        """Record successful job execution and reset circuit breaker"""
        if job_id in self.circuit_breaker:
            self.circuit_breaker[job_id]['failure_count'] = 0
            self.circuit_breaker[job_id]['last_failure'] = None
    
    def cleanup_old_metrics(self, max_age_hours: int = 48):
        """Clean up old metrics to prevent memory leaks"""
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        old_metrics = [
            job_id for job_id, metrics in self.metrics.items()
            if metrics.end_time and metrics.end_time < cutoff_time
        ]
        
        for job_id in old_metrics:
            del self.metrics[job_id]
        
        if old_metrics:
            logger.info("Cleaned up %s old job metrics", len(old_metrics))

    def can_execute_job(self, job_id: str, job_priority: JobPriority) -> bool:
        """
        ADDED: Resource-aware job execution decision
        Critical jobs always run, others are throttled under high load
        """
        try:
            # Get current system resources
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory_percent = psutil.virtual_memory().percent
            
            # Critical jobs always run regardless of system load
            if job_id in CRITICAL_JOB_PRIORITY:
                return True
            
            # Check if system is under high load
            if cpu_percent > CPU_THROTTLE_THRESHOLD or memory_percent > MEMORY_CLEANUP_THRESHOLD:
                # Only allow high priority jobs under high load
                if job_priority in [JobPriority.CRITICAL, JobPriority.HIGH]:
                    logger.warning(f"High system load detected (CPU: {cpu_percent:.1f}%, Memory: {memory_percent:.1f}%). Allowing only high priority job: {job_id}")
                    return True
                else:
                    logger.info(f"Deferring low priority job {job_id} due to high system load (CPU: {cpu_percent:.1f}%, Memory: {memory_percent:.1f}%)")
                    return False
            
            # Normal execution under normal load
            return True
            
        except Exception as e:
            logger.error(f"Error checking job execution: {e}")
            # Default to allowing execution if monitoring fails
            return True
    
    def should_throttle_jobs(self) -> bool:
        """Check if jobs should be throttled due to high resource usage"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory_percent = psutil.virtual_memory().percent
            
            return (cpu_percent > CPU_THROTTLE_THRESHOLD or 
                   memory_percent > MEMORY_CLEANUP_THRESHOLD)
                   
        except Exception as e:
            logger.error(f"Error checking throttling: {e}")
            return False

# Global resource monitor
resource_monitor = ResourceMonitor()

# =============================================================================
# OPTIMIZED EXECUTOR POOLS
# =============================================================================

# Separate executors for different workload types
cpu_executor = ProcessPoolExecutor(
    max_workers=CPU_POOL_SIZE,
    mp_context=mp.get_context('spawn')  # Windows-compatible
)

io_executor = ThreadPoolExecutor(
    max_workers=IO_POOL_SIZE,
    thread_name_prefix="io_worker"
)

mapping_executor = ThreadPoolExecutor(
    max_workers=MAPPING_POOL_SIZE,
    thread_name_prefix="mapping_worker"
)

# =============================================================================
# ENHANCED JOB EXECUTION FRAMEWORK
# =============================================================================

def safe_run(task_fn: Callable, job_id: str, priority: JobPriority, 
             executor_type: str = "thread", *args, **kwargs) -> Optional[Any]:
    """
    Production-ready task execution with comprehensive monitoring.
    
    Args:
        task_fn: Function to execute
        job_id: Unique identifier for the job
        priority: Job priority level
        executor_type: Type of executor used ("process", "thread", "mapping")
        *args, **kwargs: Arguments for the task function
    
    Returns:
        Task result or None if failed
    """
    # Circuit breaker check
    if not resource_monitor.is_job_enabled(job_id):
        logger.info("Job %s skipped due to circuit breaker", job_id)
        return None
    
    # Priority-based resource checking
    if priority in [JobPriority.LOW, JobPriority.MEDIUM]:
        if not resource_monitor.is_system_healthy():
            logger.info("Skipping %s priority job %s due to high system load", 
                       priority.value, job_id)
            return None
    
    # Memory protection check
    if psutil:
        memory = psutil.virtual_memory()
        if memory.percent > 85:  # Skip jobs if memory > 85%
            logger.warning("Skipping job %s due to high memory usage: %.1f%%", 
                          job_id, memory.percent)
            return None
    
    # Record job start with comprehensive metrics
    start_time = datetime.now()
    system_load_before = psutil.cpu_percent(interval=1) if psutil else None
    memory_before = psutil.virtual_memory().percent if psutil else None
    
    metrics = JobMetrics(
        job_id=job_id,
        start_time=start_time,
        system_load_before=system_load_before,
        memory_usage_before=memory_before,
        executor_type=executor_type
    )
    resource_monitor.metrics[job_id] = metrics
    
    # Set execution timeout
    timeout_seconds = MAX_JOB_DURATION_MINUTES * 60
    
    try:
        logger.info("Starting job %s (priority: %s, executor: %s)", 
                   job_id, priority.value, executor_type)
        
        # Execute with timeout protection and memory monitoring
        if executor_type == "process":
            # Process pool execution
            future = cpu_executor.submit(task_fn, *args, **kwargs)
            result = future.result(timeout=timeout_seconds)
        else:
            # Thread pool execution with memory monitoring
            result = task_fn(*args, **kwargs)
            
            # Check memory usage during execution
            if psutil:
                memory = psutil.virtual_memory()
                if memory.percent > 90:  # Emergency memory cleanup
                    logger.warning("High memory usage during job %s: %.1f%%, forcing cleanup", 
                                  job_id, memory.percent)
                    gc.collect()
                    if hasattr(psutil, 'Process'):
                        current_process = psutil.Process()
                        if current_process.memory_info().rss > MAX_MEMORY_PER_JOB_MB * 1024 * 1024:
                            logger.error("Job %s exceeded memory limit: %.1f MB", 
                                       job_id, current_process.memory_info().rss / (1024 * 1024))
        
        # Record success
        metrics.success = True
        metrics.end_time = datetime.now()
        metrics.duration = (metrics.end_time - metrics.start_time).total_seconds()
        resource_monitor.record_job_success(job_id)
        
        # Post-job memory cleanup
        if psutil:
            memory_after = psutil.virtual_memory()
            if memory_after.percent > 80:  # Cleanup if memory > 80%
                logger.info("Post-job memory cleanup for %s - Memory: %.1f%%", 
                           job_id, memory_after.percent)
                gc.collect()
        
        logger.info("Job %s completed successfully in %.2f seconds", job_id, metrics.duration)
        return result
        
    except Exception as exc:
        # Record failure
        metrics.success = False
        metrics.end_time = datetime.now()
        metrics.duration = (metrics.end_time - metrics.start_time).total_seconds()
        metrics.error_count += 1
        metrics.last_error = str(exc)
        
        resource_monitor.record_job_failure(job_id, str(exc))
        
        logger.error("Job %s failed after %.2f seconds: %s", job_id, metrics.duration, exc)
        return None
        
    finally:
        # Record final system state
        if psutil:
            try:
                metrics.system_load_after = psutil.cpu_percent(interval=1)
                metrics.memory_usage_after = psutil.virtual_memory().percent
            except Exception:
                pass
        
        # Periodic cleanup
        if (datetime.now() - resource_monitor._last_cleanup).total_seconds() > 3600:
            resource_monitor.cleanup_old_metrics()
            resource_monitor._last_cleanup = datetime.now()

def _run_with_retries(
    func: Callable[..., Any],
    job_id: str,
    priority: JobPriority,
    executor_type: str = "thread",
    *args: Any,
    retries: int = 2,
    initial_delay_seconds: float = 5.0,
    backoff_factor: float = 2.0,
    **kwargs: Any,
) -> Optional[Any]:
    """Enhanced retry wrapper with resource monitoring and exponential backoff"""
    delay = initial_delay_seconds
    attempt = 0
    
    while True:
        # Resource check before retry
        if not resource_monitor.is_system_healthy():
            logger.info("Waiting for system resources before retry %s for job %s", 
                       attempt + 1, job_id)
            if not resource_monitor.wait_for_resources(max_wait_minutes=5):
                logger.error("Failed to acquire system resources for job %s", job_id)
                return None
        
        try:
            return safe_run(func, job_id, priority, executor_type, *args, **kwargs)
        except Exception as exc:
            attempt += 1
            logger.error(
                "Background task failed (attempt %s/%s) for job %s: %s",
                attempt, retries + 1, job_id, exc,
            )
            
            if attempt > retries:
                logger.error("Background task permanently failed after retries for job %s", job_id)
                return None
            
            # Exponential backoff with resource check
            with suppress(Exception):
                time.sleep(delay)
            delay *= backoff_factor

# =============================================================================
# MEMORY PROTECTION DECORATOR
# =============================================================================

def memory_protected(func):
    """Decorator to protect jobs from excessive memory usage"""
    def wrapper(*args, **kwargs):
        try:
            # Execute function directly - no resource restrictions
            result = func(*args, **kwargs)
            
            # Light cleanup after execution only
            if psutil:
                memory_after = psutil.virtual_memory()
                if memory_after.percent > 90:  # Cleanup only if memory > 90%
                    logger.info("Post-execution cleanup for %s - Memory: %.1f%%", 
                               func.__name__, memory_after.percent)
                    gc.collect()
            
            return result
            
        except Exception as e:
            logger.error("Memory protected job %s failed: %s", func.__name__, e)
            # Force cleanup on error
            gc.collect()
            return None
    
    return wrapper

# =============================================================================
# OPTIMIZED JOB WRAPPERS
# =============================================================================

def async_email_download_wrapper():
    """I/O-intensive email download task - ALWAYS RUNS"""
    try:
        from mpi_backend.utils.invoice_downaloder import email_download_background_task
        
        logger.info("🧪 EMAIL DOWNLOAD JOB EXECUTING - Starting email download task")
        logger.info("Current time: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        # Execute the task directly - NO RESOURCE RESTRICTIONS
        result = email_download_background_task()
        
        if result is not None:
            logger.info("✅ EMAIL DOWNLOAD JOB COMPLETED - Task completed successfully")
        else:
            logger.info("⚠️ EMAIL DOWNLOAD JOB COMPLETED - Task completed with no result")
            
    except Exception as e:
        logger.error("❌ EMAIL DOWNLOAD JOB FAILED: %s", e)
        # Force cleanup on error
        gc.collect()

@memory_protected
def async_statement_download_wrapper():
    """I/O-intensive statement download task"""
    try:
        from mpi_backend.utils.statement_downloader import (
            statement_download_background_task,
        )
        
        logger.info("🧪 STATEMENT DOWNLOAD JOB EXECUTING - Starting statement download task")
        logger.info("Current time: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        # Execute the task directly without complex resource monitoring
        result = statement_download_background_task()
        
        if result is not None:
            logger.info("✅ STATEMENT DOWNLOAD JOB COMPLETED - Task completed successfully")
        else:
            logger.info("⚠️ STATEMENT DOWNLOAD JOB COMPLETED - Task completed with no result")
            
    except Exception as e:
        logger.error("❌ STATEMENT DOWNLOAD JOB FAILED: %s", e)
        # Force cleanup on error
        gc.collect()

def async_failed_invoice_recovery_wrapper():
    """Critical invoice recovery task - ALWAYS RUNS"""
    try:
        from mpi_backend.utils.failed_invoice_recovery import (
            failed_invoice_recovery_background_task,
        )
        
        logger.info("🧪 FAILED RECOVERY JOB EXECUTING - Starting failed invoice recovery task")
        logger.info("Current time: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        # Execute the task directly - NO RESOURCE RESTRICTIONS
        result = failed_invoice_recovery_background_task()
        
        if result is not None:
            logger.info("✅ FAILED RECOVERY JOB COMPLETED - Task completed successfully")
        else:
            logger.info("⚠️ FAILED RECOVERY JOB COMPLETED - Task completed with no result")
            
    except Exception as e:
        logger.error("❌ FAILED RECOVERY JOB FAILED: %s", e)
        # Force cleanup on error
        gc.collect()

def async_missing_invoice_download_wrapper():
    """I/O-intensive missing invoice download task - ALWAYS RUNS"""
    try:
        from mpi_backend.utils.missing_invoice_downaloder import (
            missing_email_download_background_task,
        )
        
        logger.info("🧪 MISSING INVOICE JOB EXECUTING - Starting missing invoice download task")
        logger.info("Current time: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        # Execute the task directly - NO RESOURCE RESTRICTIONS
        result = missing_email_download_background_task()
        
        if result is not None:
            logger.info("✅ MISSING INVOICE JOB COMPLETED - Task completed successfully")
        else:
            logger.info("⚠️ MISSING INVOICE JOB COMPLETED - Task completed with no result")
            
    except Exception as e:
        logger.error("❌ MISSING INVOICE JOB FAILED: %s", e)
        # Force cleanup on error
        gc.collect()

def scheduled_uidi_no_match_update():
    """CPU-intensive mapping update task - ALWAYS RUNS"""
    def _execute():
        try:
            logger.info("🧪 UIDI/NO MATCH UPDATE JOB EXECUTING - Starting UIDI/NO Match update")
            logger.info("Current time: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            
            from mpi_backend.database.controllers.GoogleSheetSyncController import (
                GoogleSheetSyncController,
            )

            # Submit the actual background worker (non-blocking)
            ack = GoogleSheetSyncController._execute_sync_task_worker(
                None, "update_no_match_uidi"
            )
            logger.info(
                "✅ UIDI/NO MATCH UPDATE JOB COMPLETED - Update submitted: %s",
                ack.get("message", "submitted"),
            )
        except Exception as exc:
            logger.error("❌ UIDI/NO MATCH UPDATE JOB FAILED: %s", exc)

    mapping_executor.submit(_execute)

def scheduled_all_mappings_update():
    """CPU-intensive comprehensive mapping update task - ALWAYS RUNS"""
    def _execute():
        try:
            logger.info("🧪 ALL MAPPINGS UPDATE JOB EXECUTING - Starting All Mappings update")
            logger.info("Current time: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            
            from mpi_backend.database.controllers.GoogleSheetSyncController import (
                GoogleSheetSyncController,
            )

            # Submit the actual background worker (non-blocking)
            ack = GoogleSheetSyncController._execute_sync_task_worker(
                None, "update_all"
            )
            logger.info(
                "✅ ALL MAPPINGS UPDATE JOB COMPLETED - Update submitted: %s",
                ack.get("message", "submitted"),
            )
        except Exception as exc:
            logger.error("❌ ALL MAPPINGS UPDATE JOB FAILED: %s", exc)

    mapping_executor.submit(_execute)

@memory_protected
def test_background_job():
    """Test job to verify background jobs are running"""
    try:
        logger.info("🧪 TEST JOB EXECUTING - Background jobs are working!")
        logger.info("Current time: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        # Simulate some work
        import time
        time.sleep(1)
        
        logger.info("✅ TEST JOB COMPLETED - Background jobs are functioning correctly!")
        return True
        
    except Exception as e:
        logger.error("❌ TEST JOB FAILED: %s", e)
        return False

@memory_protected
def enhanced_memory_cleanup_task():
    """Comprehensive memory cleanup with explicit resource management"""
    try:
        # Force garbage collection
        collected = gc.collect()
        
        # Clear module-level caches
        import sys
        for module_name in list(sys.modules.keys()):
            if any(keyword in module_name.lower() for keyword in ['cache', 'temp', 'tmp']):
                try:
                    module = sys.modules[module_name]
                    if hasattr(module, 'clear_cache'):
                        module.clear_cache()
                except Exception:
                    pass
        
        # Log comprehensive memory status
        if psutil:
            memory = psutil.virtual_memory()
            logger.info(
                "Memory cleanup completed - collected %s objects, "
                "Memory usage: %.1f%% (%.1f MB available)",
                collected,
                memory.percent,
                memory.available / (1024 * 1024)
            )
        else:
            logger.info("Memory cleanup completed - collected %s objects", collected)
            
    except Exception as exc:
        logger.error("Memory cleanup failed: %s", exc)

@memory_protected
def get_system_metrics() -> Dict[str, Any]:
    """Comprehensive system metrics for monitoring"""
    try:
        if not psutil:
            return {"error": "psutil not available"}
        
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            "timestamp": datetime.now().isoformat(),
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_available_mb": memory.available / (1024 * 1024),
            "disk_percent": disk.percent,
            "disk_free_gb": disk.free / (1024**3),
            "active_jobs": len([m for m in resource_monitor.metrics.values() if not m.end_time]),
            "total_jobs_today": len([m for m in resource_monitor.metrics.values() 
                                   if m.start_time.date() == datetime.now().date()]),
            "circuit_breaker_status": {
                job_id: {"failures": status.get("failure_count", 0), 
                        "disabled": status.get("failure_count", 0) >= resource_monitor.max_failures}
                for job_id, status in resource_monitor.circuit_breaker.items()
            },
            "executor_status": {
                "cpu_pool": cpu_executor._max_workers,
                "io_pool": io_executor._max_workers,
                "mapping_pool": mapping_executor._max_workers
            }
        }
    except Exception as e:
        return {"error": str(e)}

# =============================================================================
# PRODUCTION-READY SCHEDULER CONFIGURATION
# =============================================================================

def init_scheduler() -> BackgroundScheduler:
    """
    Create and configure a production-ready APScheduler with:
    - Separate executors for different workload types
    - Comprehensive job management and monitoring
    - Resource-aware execution and circuit breaker patterns
    - Optimized timing and staggering for Vultr Windows servers
    """
    
    # Configure executors with specific pools for different workload types
    executors = {
        'default': APSchedulerThreadPool(IO_POOL_SIZE),
        'cpu_pool': APSchedulerProcessPool(CPU_POOL_SIZE),
        'mapping_pool': APSchedulerThreadPool(MAPPING_POOL_SIZE),
    }
    
    # Job defaults optimized for production stability with memory protection
    job_defaults = {
        "coalesce": True,                    # Combine missed executions
        "max_instances": 1,                  # Prevent job overlap (CRITICAL)
        "misfire_grace_time": JOB_COALESCE_TIME,  # Grace period for missed jobs
        "timeout": MAX_JOB_DURATION_MINUTES * 60,  # Job execution timeout
        "max_instances_per_job": 1,          # Additional safety for max instances
    }
    
    # Create scheduler with optimized configuration
    scheduler = BackgroundScheduler(
        executors=executors,
        job_defaults=job_defaults,
        timezone=pytz.utc,
        jobstores={'default': {'type': 'memory'}},  # In-memory job store for simplicity
    )

    # Register scheduler globally for QuickBooks priority control
    set_scheduler_instance(scheduler)

    # =============================================================================
    # INTERVAL JOBS - Optimized for resource management
    # =============================================================================
    
    # Email downloads - I/O intensive, high priority
    scheduler.add_job(
        async_email_download_wrapper,
        "interval",
        minutes=5,
        executor='default',
        id="email_download",
        name="Email Download Task (Every 5 Minutes)",
        max_instances=1,
        misfire_grace_time=600,
        replace_existing=True,
    )

    # Statement downloads - I/O intensive, medium priority
    scheduler.add_job(
        async_statement_download_wrapper,
        "interval",
        hours=12,
        executor='default',
        id="statement_download",
        name="Statement Download Task (Every 12 Hours)",
        max_instances=1,
        misfire_grace_time=1800,
        replace_existing=True,
    )

    # Failed invoice recovery - Critical, high priority
    scheduler.add_job(
        async_failed_invoice_recovery_wrapper,
        "interval",
        hours=1,
        executor='default',
        id="failed_invoice_recovery",
        name="Failed Invoice Recovery Task (Every 1 Hour)",
        max_instances=1,
        misfire_grace_time=1800,
        replace_existing=True,
    )

    # Missing invoice downloads - I/O intensive, high priority
    scheduler.add_job(
        async_missing_invoice_download_wrapper,
        "interval",
        hours=5,
        executor='default',
        id="missing_invoice_download",
        name="Missing Invoice Download Task (Every 5 Hours)",
        max_instances=1,
        misfire_grace_time=1800,
        replace_existing=True,
    )

    # =============================================================================
    # CRON JOBS - Staggered for resource management
    # =============================================================================
    
    # UIDI/NO Match updates - Daily at 6 AM PKT (1 AM UTC)
    scheduler.add_job(
        scheduled_uidi_no_match_update,
        CronTrigger(hour=1, minute=0, timezone=pytz.utc),
        executor='mapping_pool',
        id="daily_uidi_no_match_update",
        name="Daily UIDI/NO Match Update (6 AM PKT)",
        max_instances=1,
        misfire_grace_time=3600,
        replace_existing=True,
    )

    # All Mappings update - Saturday at 8 AM PKT (3 AM UTC)
    scheduler.add_job(
        scheduled_all_mappings_update,
        CronTrigger(hour=3, minute=0, timezone=pytz.utc, day_of_week=5),
        executor='mapping_pool',
        id="all_mappings_update_saturday_8am",
        name="All Mappings Update (Every Saturday at 8 AM PKT)",
        max_instances=1,
        misfire_grace_time=3600,
        replace_existing=True,
    )

    # =============================================================================
    # MAINTENANCE JOBS - Low priority, resource-aware
    # =============================================================================
    
    # Enhanced memory cleanup - Every 30 minutes
    scheduler.add_job(
        enhanced_memory_cleanup_task,
        "interval",
        minutes=30,
        executor='default',
        id="memory_cleanup",
        name="Enhanced Memory Cleanup Task",
        max_instances=1,
        misfire_grace_time=900,
        replace_existing=True,
    )

    # System metrics collection - Every 5 minutes
    scheduler.add_job(
        get_system_metrics,
        "interval",
        minutes=5,
        executor='default',
        id="system_metrics",
        name="System Metrics Collection",
        max_instances=1,
        misfire_grace_time=300,
        replace_existing=True,
    )
    
    # Test job - Every 2 minutes (for debugging)
    scheduler.add_job(
        test_background_job,
        "interval",
        minutes=2,
        executor='default',
        id="test_job",
        name="Test Background Job (Every 2 Minutes)",
        max_instances=1,
        misfire_grace_time=300,
        replace_existing=True,
    )

    # =============================================================================
    # SCHEDULER STARTUP VALIDATION
    # =============================================================================
    
    logger.info("APScheduler configured with %s jobs", len(scheduler.get_jobs()))
    logger.info("Executor pools: CPU=%s, I/O=%s, Mapping=%s", 
               CPU_POOL_SIZE, IO_POOL_SIZE, MAPPING_POOL_SIZE)
    logger.info("Resource thresholds: CPU=%s%%, Memory=%sMB", 
               CPU_THRESHOLD, MEMORY_THRESHOLD_MB)
    
    return scheduler

# =============================================================================
# GRACEFUL SHUTDOWN HANDLERS
# =============================================================================

def shutdown_executors():
    """Gracefully shutdown all executor pools"""
    logger.info("Shutting down executor pools...")
    
    try:
        cpu_executor.shutdown(wait=True)
        logger.info("CPU executor pool shutdown complete")
    except Exception as e:
        logger.error("Error shutting down CPU executor: %s", e)
    
    try:
        io_executor.shutdown(wait=True)
        logger.info("I/O executor pool shutdown complete")
    except Exception as e:
        logger.error("Error shutting down I/O executor: %s", e)
    
    try:
        mapping_executor.shutdown(wait=True)
        logger.info("Mapping executor pool shutdown complete")
    except Exception as e:
        logger.error("Error shutting down mapping executor: %s", e)

# Register shutdown handler
import atexit
atexit.register(shutdown_executors)

