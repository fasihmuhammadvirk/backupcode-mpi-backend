"""
Background Task Optimizer for MPI Backend
Implements proactive optimization strategies to prevent high CPU usage.
"""

import logging
import time
import threading
from typing import Dict, Any, List, Optional, Callable
from enum import Enum
import psutil

logger = logging.getLogger(__name__)

class TaskPriority(Enum):
    """Task priority levels for optimization"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class TaskOptimizer:
    """Proactive background task optimization to prevent high CPU usage"""
    
    def __init__(self):
        self.task_stats = {
            'total_tasks': 0,
            'critical_tasks': 0,
            'high_tasks': 0,
            'medium_tasks': 0,
            'low_tasks': 0,
            'paused_tasks': 0,
            'optimized_tasks': 0
        }
        self.task_queue = {
            TaskPriority.CRITICAL: [],
            TaskPriority.HIGH: [],
            TaskPriority.MEDIUM: [],
            TaskPriority.LOW: []
        }
        self.paused_tasks = set()
        self.optimization_lock = threading.Lock()
        
    def add_task(self, task_id: str, priority: TaskPriority, task_func: Callable, 
                 interval_minutes: int = 15, **kwargs):
        """Add a task with priority-based optimization"""
        try:
            task_info = {
                'id': task_id,
                'priority': priority,
                'function': task_func,
                'interval': interval_minutes,
                'last_run': 0,
                'next_run': time.time() + (interval_minutes * 60),
                'kwargs': kwargs,
                'execution_count': 0,
                'total_execution_time': 0
            }
            
            self.task_queue[priority].append(task_info)
            self.task_stats[f'{priority.value}_tasks'] += 1
            self.task_stats['total_tasks'] += 1
            
            logger.info(f"Added {priority.value} priority task: {task_id}")
            
        except Exception as e:
            logger.error(f"Error adding task {task_id}: {e}")
    
    def optimize_task_execution(self):
        """Optimize task execution based on system resources"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory_percent = psutil.virtual_memory().percent
            
            with self.optimization_lock:
                if cpu_percent > 80 or memory_percent > 80:
                    # High resource usage - pause low priority tasks
                    self._pause_low_priority_tasks()
                    logger.info(f"High resource usage detected - CPU: {cpu_percent}%, Memory: {memory_percent}% - Pausing low priority tasks")
                    
                elif cpu_percent > 60 or memory_percent > 60:
                    # Moderate resource usage - slow down medium priority tasks
                    self._slow_down_medium_tasks()
                    logger.info(f"Moderate resource usage detected - CPU: {cpu_percent}%, Memory: {memory_percent}% - Slowing down medium priority tasks")
                    
                else:
                    # Normal resource usage - resume all tasks
                    self._resume_all_tasks()
                    logger.debug("Normal resource usage - all tasks resumed")
                    
        except Exception as e:
            logger.error(f"Error optimizing task execution: {e}")
    
    def _pause_low_priority_tasks(self):
        """Pause low and medium priority tasks during high resource usage"""
        try:
            # Pause low priority tasks
            for task_info in self.task_queue[TaskPriority.LOW]:
                if task_info['id'] not in self.paused_tasks:
                    self.paused_tasks.add(task_info['id'])
                    self.task_stats['paused_tasks'] += 1
                    logger.info(f"Paused low priority task: {task_info['id']}")
            
            # Pause medium priority tasks
            for task_info in self.task_queue[TaskPriority.MEDIUM]:
                if task_info['id'] not in self.paused_tasks:
                    self.paused_tasks.add(task_info['id'])
                    self.task_stats['paused_tasks'] += 1
                    logger.info(f"Paused medium priority task: {task_info['id']}")
                    
        except Exception as e:
            logger.error(f"Error pausing low priority tasks: {e}")
    
    def _slow_down_medium_tasks(self):
        """Slow down medium priority tasks during moderate resource usage"""
        try:
            # Resume low priority tasks but slow down medium ones
            for task_info in self.task_queue[TaskPriority.LOW]:
                if task_info['id'] in self.paused_tasks:
                    self.paused_tasks.remove(task_info['id'])
                    self.task_stats['paused_tasks'] -= 1
                    logger.info(f"Resumed low priority task: {task_info['id']}")
            
            # Slow down medium priority tasks by increasing intervals
            for task_info in self.task_queue[TaskPriority.MEDIUM]:
                if task_info['id'] in self.paused_tasks:
                    self.paused_tasks.remove(task_info['id'])
                    self.task_stats['paused_tasks'] -= 1
                
                # Increase interval for medium priority tasks
                if task_info['interval'] < 60:  # Don't increase beyond 1 hour
                    task_info['interval'] = min(task_info['interval'] * 2, 60)
                    task_info['next_run'] = time.time() + (task_info['interval'] * 60)
                    logger.info(f"Slowed down medium priority task: {task_info['id']} - New interval: {task_info['interval']} minutes")
                    
        except Exception as e:
            logger.error(f"Error slowing down medium tasks: {e}")
    
    def _resume_all_tasks(self):
        """Resume all paused tasks when resources are normal"""
        try:
            if self.paused_tasks:
                logger.info(f"Resuming {len(self.paused_tasks)} paused tasks")
                
                # Reset medium priority task intervals
                for task_info in self.task_queue[TaskPriority.MEDIUM]:
                    if hasattr(task_info, 'original_interval'):
                        task_info['interval'] = task_info['original_interval']
                        task_info['next_run'] = time.time() + (task_info['interval'] * 60)
                
                # Clear paused tasks
                self.paused_tasks.clear()
                self.task_stats['paused_tasks'] = 0
                
        except Exception as e:
            logger.error(f"Error resuming tasks: {e}")
    
    def execute_ready_tasks(self):
        """Execute tasks that are ready to run"""
        try:
            current_time = time.time()
            executed_tasks = 0
            
            # Execute tasks by priority (critical first)
            for priority in [TaskPriority.CRITICAL, TaskPriority.HIGH, TaskPriority.MEDIUM, TaskPriority.LOW]:
                tasks_to_execute = []
                
                for task_info in self.task_queue[priority]:
                    # Skip paused tasks
                    if task_info['id'] in self.paused_tasks:
                        continue
                    
                    # Check if task is ready to run
                    if current_time >= task_info['next_run']:
                        tasks_to_execute.append(task_info)
                
                # Execute ready tasks
                for task_info in tasks_to_execute:
                    try:
                        start_time = time.time()
                        
                        # Execute task
                        task_info['function'](**task_info['kwargs'])
                        
                        # Update statistics
                        execution_time = time.time() - start_time
                        task_info['execution_count'] += 1
                        task_info['total_execution_time'] += execution_time
                        task_info['last_run'] = current_time
                        task_info['next_run'] = current_time + (task_info['interval'] * 60)
                        
                        executed_tasks += 1
                        self.task_stats['optimized_tasks'] += 1
                        
                        logger.info(f"Executed {priority.value} priority task: {task_info['id']} in {execution_time:.2f}s")
                        
                    except Exception as e:
                        logger.error(f"Error executing task {task_info['id']}: {e}")
                        # Don't update next_run for failed tasks - retry soon
                        task_info['next_run'] = current_time + 60  # Retry in 1 minute
            
            return executed_tasks
            
        except Exception as e:
            logger.error(f"Error executing ready tasks: {e}")
            return 0
    
    def get_task_optimization_stats(self) -> Dict[str, Any]:
        """Get task optimization statistics"""
        try:
            return {
                'task_stats': self.task_stats.copy(),
                'paused_tasks_count': len(self.paused_tasks),
                'paused_task_ids': list(self.paused_tasks),
                'queue_sizes': {
                    priority.value: len(tasks) 
                    for priority, tasks in self.task_queue.items()
                },
                'next_task_execution': self._get_next_task_execution_time()
            }
        except Exception as e:
            logger.error(f"Error getting task optimization stats: {e}")
            return {}
    
    def _get_next_task_execution_time(self) -> Dict[str, Any]:
        """Get information about next task executions"""
        try:
            next_executions = {}
            
            for priority, tasks in self.task_queue.items():
                if tasks:
                    # Find next execution time for this priority
                    next_times = [task['next_run'] for task in tasks if task['id'] not in self.paused_tasks]
                    if next_times:
                        next_executions[priority.value] = {
                            'next_execution': min(next_times),
                            'time_until_next': min(next_times) - time.time()
                        }
            
            return next_executions
            
        except Exception as e:
            logger.error(f"Error getting next task execution times: {e}")
            return {}
    
    def clear_completed_tasks(self):
        """Clear completed tasks to free memory"""
        try:
            cleared_count = 0
            
            for priority in self.task_queue:
                original_count = len(self.task_queue[priority])
                
                # Remove tasks that haven't run in 24 hours
                cutoff_time = time.time() - (24 * 60 * 60)
                self.task_queue[priority] = [
                    task for task in self.task_queue[priority]
                    if task['last_run'] > cutoff_time or task['last_run'] == 0
                ]
                
                cleared_count += original_count - len(self.task_queue[priority])
            
            if cleared_count > 0:
                logger.info(f"Cleared {cleared_count} completed tasks")
                
        except Exception as e:
            logger.error(f"Error clearing completed tasks: {e}")

# Global task optimizer instance
task_optimizer = TaskOptimizer()
