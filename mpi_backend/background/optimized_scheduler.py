"""
Optimized Background Task Scheduler for MPI Backend
Implements resource monitoring, task prioritization, and automatic scaling.
"""

import logging
import time
import psutil
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import Callable, Any, Optional, Dict
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timedelta
import multiprocessing as mp
import threading

from mpi_backend.config.performance_config import (
    MAX_CPU_USAGE,
    MAX_MEMORY_USAGE,
    MAX_CONCURRENT_TASKS,
    TASK_PRIORITIES,
    RESOURCE_CHECK_INTERVAL,
    RESOURCE_SAMPLE_COUNT
)

logger = logging.getLogger(__name__)

class TaskPriority(Enum):
    """Task priority levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

@dataclass
class TaskMetrics:
    """Task execution metrics for monitoring"""
    task_id: str
    priority: TaskPriority
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: Optional[float] = None
    success: bool = False
    error_count: int = 0
    last_error: Optional[str] = None
    cpu_usage_before: Optional[float] = None
    cpu_usage_after: Optional[float] = None
    memory_usage_before: Optional[float] = None
    memory_usage_after: Optional[float] = None
    executor_type: Optional[str] = None

class ResourceMonitor:
    """Advanced system resource monitoring with automatic scaling"""
    
    def __init__(self):
        self.metrics: Dict[str, TaskMetrics] = {}
        self.circuit_breaker: Dict[str, Dict] = {}
        self.max_failures = 3
        self.failure_window_hours = 24
        self._last_cleanup = datetime.now()
        self._lock = threading.Lock()
        
        # Resource thresholds
        self.cpu_threshold = MAX_CPU_USAGE
        self.memory_threshold = MAX_MEMORY_USAGE
        
        # Dynamic scaling
        self.current_scale_factor = 1.0
        self.min_scale_factor = 0.5
        self.max_scale_factor = 2.0
        
    def is_system_healthy(self) -> bool:
        """Comprehensive system health check with multiple samples"""
        try:
            with self._lock:
                # CPU check with multiple samples for accuracy
                cpu_samples = []
                for _ in range(RESOURCE_SAMPLE_COUNT):
                    cpu_samples.append(psutil.cpu_percent(interval=0.2))
                cpu_percent = sum(cpu_samples) / len(cpu_samples)
                
                # Memory check
                memory = psutil.virtual_memory()
                memory_percent = memory.percent
                
                # Disk check
                disk = psutil.disk_usage('/')
                disk_percent = disk.percent
                
                # Comprehensive health assessment
                is_healthy = (
                    cpu_percent < self.cpu_threshold and
                    memory_percent < self.memory_threshold and
                    disk_percent < 90
                )
                
                if not is_healthy:
                    logger.warning(
                        "System resources low - CPU: %.1f%%, RAM: %.1f%%, "
                        "Disk: %.1f%%",
                        cpu_percent, memory_percent, disk_percent
                    )
                
                # Adjust scale factor based on resource usage
                self._adjust_scale_factor(cpu_percent, memory_percent)
                
                return is_healthy
                
        except Exception as e:
            logger.error("Failed to check system health: %s", e)
            return False
    
    def _adjust_scale_factor(self, cpu_percent: float, memory_percent: float):
        """Dynamically adjust scale factor based on resource usage"""
        try:
            # Calculate resource pressure (0.0 to 1.0)
            cpu_pressure = cpu_percent / 100.0
            memory_pressure = memory_percent / 100.0
            resource_pressure = max(cpu_pressure, memory_pressure)
            
            # Adjust scale factor based on pressure
            if resource_pressure > 0.8:  # High pressure
                self.current_scale_factor = max(
                    self.min_scale_factor,
                    self.current_scale_factor * 0.9
                )
                logger.info(
                    "Reducing scale factor to %.2f due to high resource pressure",
                    self.current_scale_factor
                )
            elif resource_pressure < 0.4:  # Low pressure
                self.current_scale_factor = min(
                    self.max_scale_factor,
                    self.current_scale_factor * 1.1
                )
                logger.info(
                    "Increasing scale factor to %.2f due to low resource pressure",
                    self.current_scale_factor
                )
                
        except Exception as e:
            logger.error("Error adjusting scale factor: %s", e)
    
    def get_current_capacity(self) -> int:
        """Get current task capacity based on scale factor"""
        base_capacity = MAX_CONCURRENT_TASKS
        return max(1, int(base_capacity * self.current_scale_factor))
    
    def wait_for_resources(self, priority: TaskPriority, max_wait_minutes: int = 15) -> bool:
        """Smart resource waiting with priority-based queuing"""
        start_time = time.time()
        max_wait_seconds = max_wait_minutes * 60
        wait_interval = 2  # Start with 2 second intervals
        
        # Priority-based waiting
        priority_wait_multiplier = {
            TaskPriority.CRITICAL: 1.0,    # No extra wait
            TaskPriority.HIGH: 1.2,        # 20% extra wait
            TaskPriority.MEDIUM: 1.5,      # 50% extra wait
            TaskPriority.LOW: 2.0,         # 100% extra wait
        }
        
        adjusted_max_wait = max_wait_seconds * priority_wait_multiplier.get(priority, 1.0)
        
        while time.time() - start_time < adjusted_max_wait:
            if self.is_system_healthy():
                return True
            
            remaining = adjusted_max_wait - (time.time() - start_time)
            logger.info(
                "Waiting for system resources (%.0f seconds remaining, "
                "priority: %s)...",
                remaining, priority.value
            )
            
            time.sleep(wait_interval)
            wait_interval = min(wait_interval * 1.2, 15)  # Exponential backoff
        
        logger.warning(
            "Timed out waiting for system resources (priority: %s)",
            priority.value
        )
        return False
    
    def record_task_start(self, task_id: str, priority: TaskPriority) -> TaskMetrics:
        """Record task start and current resource usage"""
        with self._lock:
            metrics = TaskMetrics(
                task_id=task_id,
                priority=priority,
                start_time=datetime.now(),
                cpu_usage_before=psutil.cpu_percent(interval=0.1),
                memory_usage_before=psutil.virtual_memory().percent
            )
            self.metrics[task_id] = metrics
            return metrics
    
    def record_task_completion(self, task_id: str, success: bool, 
                              error: Optional[str] = None):
        """Record task completion and final resource usage"""
        with self._lock:
            if task_id in self.metrics:
                metrics = self.metrics[task_id]
                metrics.end_time = datetime.now()
                metrics.duration = (metrics.end_time - metrics.start_time).total_seconds()
                metrics.success = success
                
                if not success and error:
                    metrics.error_count += 1
                    metrics.last_error = error
                
                # Record final resource usage
                metrics.cpu_usage_after = psutil.cpu_percent(interval=0.1)
                metrics.memory_usage_after = psutil.virtual_memory().percent
                
                # Log resource impact
                if metrics.duration and metrics.duration > 60:  # Long-running tasks
                    logger.info(
                        "Task %s completed in %.1fs - CPU: %.1f%% -> %.1f%%, "
                        "Memory: %.1f%% -> %.1f%%",
                        task_id, metrics.duration,
                        metrics.cpu_usage_before or 0,
                        metrics.cpu_usage_after or 0,
                        metrics.memory_usage_before or 0,
                        metrics.memory_usage_after or 0
                    )
    
    def cleanup_old_metrics(self, max_age_hours: int = 24):
        """Clean up old task metrics"""
        try:
            current_time = datetime.now()
            cutoff_time = current_time - timedelta(hours=max_age_hours)
            
            with self._lock:
                old_task_ids = [
                    task_id for task_id, metrics in self.metrics.items()
                    if metrics.start_time < cutoff_time
                ]
                
                for task_id in old_task_ids:
                    del self.metrics[task_id]
                
                if old_task_ids:
                    logger.info(
                        "Cleaned up %d old task metrics (older than %d hours)",
                        len(old_task_ids), max_age_hours
                    )
                    
        except Exception as e:
            logger.error("Error cleaning up old metrics: %s", e)

class OptimizedScheduler:
    """Optimized background task scheduler with resource management"""
    
    def __init__(self):
        self.scheduler = None
        self.resource_monitor = ResourceMonitor()
        self.executor_pools = {}
        self.task_queue = {}
        self._lock = threading.Lock()
        self._shutdown_event = threading.Event()
        
        # Initialize executor pools
        self._initialize_executors()
        
        # Start resource monitoring thread
        self._start_resource_monitoring()
    
    def _initialize_executors(self):
        """Initialize executor pools with optimized settings"""
        try:
            # CPU-intensive tasks (PDF processing, data analysis)
            self.executor_pools['cpu'] = ProcessPoolExecutor(
                max_workers=2,  # Limited to prevent CPU overload
                mp_context=mp.get_context('spawn')  # More stable on Windows
            )
            
            # I/O-intensive tasks (database operations, file downloads)
            self.executor_pools['io'] = ThreadPoolExecutor(
                max_workers=8,  # More threads for I/O operations
                thread_name_prefix="IOWorker"
            )
            
            # Mapping operations (dedicated pool)
            self.executor_pools['mapping'] = ThreadPoolExecutor(
                max_workers=4,
                thread_name_prefix="MappingWorker"
            )
            
            logger.info("Executor pools initialized successfully")
            
        except Exception as e:
            logger.error("Failed to initialize executor pools: %s", e)
            raise
    
    def _start_resource_monitoring(self):
        """Start background resource monitoring"""
        def monitor_loop():
            while not self._shutdown_event.is_set():
                try:
                    # Check system health
                    self.resource_monitor.is_system_healthy()
                    
                    # Cleanup old metrics
                    self.resource_monitor.cleanup_old_metrics()
                    
                    # Log current status
                    if self.scheduler:
                        job_count = len(self.scheduler.get_jobs())
                        logger.debug(
                            "Scheduler status - Jobs: %d, Scale factor: %.2f, "
                            "Capacity: %d",
                            job_count,
                            self.resource_monitor.current_scale_factor,
                            self.resource_monitor.get_current_capacity()
                        )
                    
                    time.sleep(RESOURCE_CHECK_INTERVAL)
                    
                except Exception as e:
                    logger.error("Error in resource monitoring loop: %s", e)
                    time.sleep(RESOURCE_CHECK_INTERVAL * 2)
        
        monitor_thread = threading.Thread(
            target=monitor_loop,
            name="ResourceMonitor",
            daemon=True
        )
        monitor_thread.start()
        logger.info("Resource monitoring started")
    
    def add_job(self, func: Callable, trigger: Any, priority: TaskPriority = TaskPriority.MEDIUM,
                **kwargs) -> str:
        """Add a job to the scheduler with priority and resource management"""
        try:
            # Generate unique job ID
            job_id = f"{func.__name__}_{int(time.time())}"
            
            # Check if we have capacity for this priority
            if not self._can_accept_task(priority):
                logger.warning(
                    "Cannot accept task %s (priority: %s) - insufficient capacity",
                    job_id, priority.value
                )
                return None
            
            # Add job to scheduler
            if self.scheduler:
                job = self.scheduler.add_job(
                    func=func,
                    trigger=trigger,
                    id=job_id,
                    **kwargs
                )
                
                # Record in task queue
                with self._lock:
                    self.task_queue[job_id] = {
                        'priority': priority,
                        'status': 'scheduled',
                        'created_at': datetime.now()
                    }
                
                logger.info(
                    "Job %s added with priority %s",
                    job_id, priority.value
                )
                
                return job_id
            
        except Exception as e:
            logger.error("Failed to add job %s: %s", job_id, e)
            return None
    
    def _can_accept_task(self, priority: TaskPriority) -> bool:
        """Check if we can accept a new task based on priority and capacity"""
        try:
            current_capacity = self.resource_monitor.get_current_capacity()
            active_tasks = len([t for t in self.task_queue.values() 
                              if t['status'] == 'running'])
            
            # Priority-based capacity allocation
            priority_capacity = {
                TaskPriority.CRITICAL: current_capacity,
                TaskPriority.HIGH: int(current_capacity * 0.8),
                TaskPriority.MEDIUM: int(current_capacity * 0.6),
                TaskPriority.LOW: int(current_capacity * 0.4),
            }
            
            available_capacity = priority_capacity.get(priority, current_capacity)
            return active_tasks < available_capacity
            
        except Exception as e:
            logger.error("Error checking task capacity: %s", e)
            return False
    
    def execute_task(self, func: Callable, *args, priority: TaskPriority = TaskPriority.MEDIUM,
                    executor_type: str = 'io', **kwargs) -> Any:
        """Execute a task with resource monitoring and priority management"""
        task_id = f"{func.__name__}_{int(time.time())}"
        
        try:
            # Wait for resources if necessary
            if not self.resource_monitor.wait_for_resources(priority):
                raise RuntimeError("Insufficient system resources")
            
            # Record task start
            metrics = self.resource_monitor.record_task_start(task_id, priority)
            metrics.executor_type = executor_type
            
            # Update task status
            with self._lock:
                if task_id in self.task_queue:
                    self.task_queue[task_id]['status'] = 'running'
            
            # Execute task
            executor = self.executor_pools.get(executor_type)
            if not executor:
                raise ValueError(f"Unknown executor type: {executor_type}")
            
            future = executor.submit(func, *args, **kwargs)
            result = future.result(timeout=TASK_PRIORITIES[priority.value]['timeout'])
            
            # Record successful completion
            self.resource_monitor.record_task_completion(task_id, True)
            
            # Update task status
            with self._lock:
                if task_id in self.task_queue:
                    self.task_queue[task_id]['status'] = 'completed'
            
            return result
            
        except Exception as e:
            # Record failure
            self.resource_monitor.record_task_completion(task_id, False, str(e))
            
            # Update task status
            with self._lock:
                if task_id in self.task_queue:
                    self.task_queue[task_id]['status'] = 'failed'
                    self.task_queue[task_id]['error'] = str(e)
            
            logger.error("Task %s failed: %s", task_id, e)
            raise
    
    def get_status(self) -> Dict[str, Any]:
        """Get current scheduler status"""
        try:
            with self._lock:
                return {
                    'scheduler_running': self.scheduler and self.scheduler.running,
                    'resource_monitor': {
                        'cpu_threshold': self.resource_monitor.cpu_threshold,
                        'memory_threshold': self.resource_monitor.memory_threshold,
                        'current_scale_factor': self.resource_monitor.current_scale_factor,
                        'current_capacity': self.resource_monitor.get_current_capacity(),
                    },
                    'executor_pools': {
                        name: {
                            'max_workers': pool._max_workers,
                            'active_threads': len(pool._threads) if hasattr(pool, '_threads') else 0,
                        }
                        for name, pool in self.executor_pools.items()
                    },
                    'task_queue': {
                        task_id: {
                            'priority': task_info['priority'].value,
                            'status': task_info['status'],
                            'created_at': task_info['created_at'].isoformat(),
                        }
                        for task_id, task_info in self.task_queue.items()
                    },
                    'metrics': {
                        'total_tasks': len(self.resource_monitor.metrics),
                        'successful_tasks': len([m for m in self.resource_monitor.metrics.values() if m.success]),
                        'failed_tasks': len([m for m in self.resource_monitor.metrics.values() if not m.success]),
                    }
                }
                
        except Exception as e:
            logger.error("Error getting scheduler status: %s", e)
            return {'error': str(e)}
    
    def shutdown(self):
        """Gracefully shutdown the scheduler"""
        try:
            logger.info("Shutting down optimized scheduler...")
            
            # Signal shutdown
            self._shutdown_event.set()
            
            # Shutdown scheduler
            if self.scheduler:
                self.scheduler.shutdown(wait=True)
            
            # Shutdown executor pools
            for name, executor in self.executor_pools.items():
                try:
                    executor.shutdown(wait=True)
                    logger.info("Executor pool %s shutdown complete", name)
                except Exception as e:
                    logger.error("Error shutting down executor pool %s: %s", name, e)
            
            logger.info("Optimized scheduler shutdown complete")
            
        except Exception as e:
            logger.error("Error during scheduler shutdown: %s", e)

# Global scheduler instance
optimized_scheduler = OptimizedScheduler()

def get_optimized_scheduler() -> OptimizedScheduler:
    """Get the global optimized scheduler instance"""
    return optimized_scheduler

def cleanup_scheduler():
    """Cleanup scheduler on application shutdown"""
    optimized_scheduler.shutdown()
