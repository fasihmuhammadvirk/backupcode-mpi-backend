#!/usr/bin/env python3
"""
Comprehensive test suite for background scheduler and async tasks.
Tests scheduler initialization, job scheduling, execution, and error handling.
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock, call
from concurrent.futures import ThreadPoolExecutor
import pytz

from mpi_backend.background.scheduler import (
    init_scheduler,
    async_email_download_wrapper,
    async_statement_download_wrapper,
    async_failed_invoice_recovery_wrapper,
    async_missing_invoice_download_wrapper,
    scheduled_uidi_no_match_update,
    scheduled_all_mappings_update,
    memory_cleanup_task,
    _run_with_retries,
    task_executor,
    email_executor,
    UTC_TZ
)


class TestBackgroundScheduler:
    """Test suite for background scheduler and async tasks."""

    @pytest.fixture
    def mock_scheduler(self):
        """Create a mock scheduler for testing."""
        mock_scheduler = Mock()
        mock_scheduler.add_job = Mock()
        mock_scheduler.start = Mock()
        mock_scheduler.shutdown = Mock()
        return mock_scheduler

    def test_init_scheduler_creates_scheduler(self):
        """Test that init_scheduler creates a scheduler with proper configuration."""
        with patch('mpi_backend.background.scheduler.BackgroundScheduler') as mock_bg_scheduler:
            mock_scheduler_instance = Mock()
            mock_bg_scheduler.return_value = mock_scheduler_instance
            
            scheduler = init_scheduler()
            
            # Verify BackgroundScheduler was created with correct config
            mock_bg_scheduler.assert_called_once()
            call_args = mock_bg_scheduler.call_args
            assert call_args[1]['timezone'] == UTC_TZ
            assert 'job_defaults' in call_args[1]
            
            # Verify jobs were added
            assert mock_scheduler_instance.add_job.call_count >= 6  # Multiple jobs

    def test_init_scheduler_job_configuration(self):
        """Test that all required jobs are configured correctly."""
        with patch('mpi_backend.background.scheduler.BackgroundScheduler') as mock_bg_scheduler:
            mock_scheduler_instance = Mock()
            mock_bg_scheduler.return_value = mock_scheduler_instance
            
            scheduler = init_scheduler()
            
            # Get all add_job calls
            job_calls = mock_scheduler_instance.add_job.call_args_list
            
            # Verify specific jobs exist
            job_ids = []
            for call in job_calls:
                if len(call) > 1 and 'id' in call[1]:
                    job_ids.append(call[1]['id'])
            
            expected_job_ids = [
                'email_download',
                'statement_download',
                'failed_invoice_recovery',
                'missing_invoice_download',
                'daily_uidi_no_match_update',
                'all_mappings_update_saturday_8am',
                'memory_cleanup'
            ]
            
            for expected_id in expected_job_ids:
                assert expected_id in job_ids

    def test_email_download_wrapper_execution(self):
        """Test async email download wrapper execution."""
        with patch('mpi_backend.background.scheduler.email_executor') as mock_executor:
            mock_executor.submit = Mock()
            
            async_email_download_wrapper()
            
            # Verify task was submitted to executor
            mock_executor.submit.assert_called_once()
            
            # Get the submitted function and call it to test
            submitted_func = mock_executor.submit.call_args[0][0]
            
            # Mock the actual download task
            with patch('mpi_backend.utils.invoice_downaloder.email_download_background_task') as mock_task:
                submitted_func()
                mock_task.assert_called_once()

    def test_statement_download_wrapper_execution(self):
        """Test async statement download wrapper execution."""
        with patch('mpi_backend.background.scheduler.email_executor') as mock_executor:
            mock_executor.submit = Mock()
            
            async_statement_download_wrapper()
            
            mock_executor.submit.assert_called_once()
            
            # Test the submitted function
            submitted_func = mock_executor.submit.call_args[0][0]
            
            with patch('mpi_backend.utils.statement_downloader.statement_download_background_task') as mock_task:
                submitted_func()
                mock_task.assert_called_once()

    def test_failed_invoice_recovery_wrapper_execution(self):
        """Test async failed invoice recovery wrapper execution."""
        with patch('mpi_backend.background.scheduler.email_executor') as mock_executor:
            mock_executor.submit = Mock()
            
            async_failed_invoice_recovery_wrapper()
            
            mock_executor.submit.assert_called_once()
            
            submitted_func = mock_executor.submit.call_args[0][0]
            
            with patch('mpi_backend.utils.failed_invoice_recovery.failed_invoice_recovery_background_task') as mock_task:
                submitted_func()
                mock_task.assert_called_once()

    def test_missing_invoice_download_wrapper_execution(self):
        """Test async missing invoice download wrapper execution."""
        with patch('mpi_backend.background.scheduler.email_executor') as mock_executor:
            mock_executor.submit = Mock()
            
            async_missing_invoice_download_wrapper()
            
            mock_executor.submit.assert_called_once()
            
            submitted_func = mock_executor.submit.call_args[0][0]
            
            with patch('mpi_backend.utils.missing_invoice_downaloder.missing_email_download_background_task') as mock_task:
                submitted_func()
                mock_task.assert_called_once()

    def test_scheduled_uidi_no_match_update(self):
        """Test scheduled UIDI/NO Match update task."""
        with patch('mpi_backend.background.scheduler.task_executor') as mock_executor:
            mock_executor.submit = Mock()
            
            scheduled_uidi_no_match_update()
            
            mock_executor.submit.assert_called_once()
            
            # Test the submitted function
            submitted_func = mock_executor.submit.call_args[0][0]
            
            with patch('mpi_backend.database.controllers.GoogleSheetSyncController.GoogleSheetSyncController') as mock_controller:
                mock_controller._execute_sync_task_worker = Mock(return_value={'message': 'success'})
                
                submitted_func()
                
                mock_controller._execute_sync_task_worker.assert_called_once_with(
                    None, "update_no_match_uidi"
                )

    def test_scheduled_all_mappings_update(self):
        """Test scheduled all mappings update task."""
        with patch('mpi_backend.background.scheduler.task_executor') as mock_executor:
            mock_executor.submit = Mock()
            
            scheduled_all_mappings_update()
            
            mock_executor.submit.assert_called_once()
            
            submitted_func = mock_executor.submit.call_args[0][0]
            
            with patch('mpi_backend.database.controllers.GoogleSheetSyncController.GoogleSheetSyncController') as mock_controller:
                mock_controller._execute_sync_task_worker = Mock(return_value={'message': 'success'})
                
                submitted_func()
                
                mock_controller._execute_sync_task_worker.assert_called_once_with(
                    None, "update_all"
                )

    def test_memory_cleanup_task(self):
        """Test memory cleanup task execution."""
        with patch('gc.collect') as mock_gc:
            mock_gc.return_value = 100  # Mock collected objects count
            
            memory_cleanup_task()
            
            mock_gc.assert_called_once()

    def test_memory_cleanup_task_exception_handling(self):
        """Test memory cleanup task handles exceptions gracefully."""
        with patch('gc.collect') as mock_gc:
            mock_gc.side_effect = Exception("GC error")
            
            # Should not raise exception
            memory_cleanup_task()
            
            mock_gc.assert_called_once()

    def test_run_with_retries_success_on_first_attempt(self):
        """Test _run_with_retries succeeds on first attempt."""
        mock_func = Mock(return_value="success")
        
        result = _run_with_retries(mock_func, "arg1", "arg2", kwarg1="value1")
        
        assert result == "success"
        mock_func.assert_called_once_with("arg1", "arg2", kwarg1="value1")

    def test_run_with_retries_success_after_failures(self):
        """Test _run_with_retries succeeds after initial failures."""
        mock_func = Mock(side_effect=[
            Exception("First failure"),
            Exception("Second failure"),
            "success"  # Third attempt succeeds
        ])
        
        with patch('time.sleep'):  # Speed up test by mocking sleep
            result = _run_with_retries(mock_func, retries=2, initial_delay_seconds=0.01)
        
        assert result == "success"
        assert mock_func.call_count == 3

    def test_run_with_retries_max_retries_exceeded(self):
        """Test _run_with_retries when max retries are exceeded."""
        mock_func = Mock(side_effect=Exception("Persistent failure"))
        
        with patch('time.sleep'):
            result = _run_with_retries(mock_func, retries=2, initial_delay_seconds=0.01)
        
        assert result is None
        assert mock_func.call_count == 3  # Initial + 2 retries

    def test_run_with_retries_backoff_timing(self):
        """Test _run_with_retries backoff timing."""
        mock_func = Mock(side_effect=Exception("Failure"))
        
        with patch('time.sleep') as mock_sleep:
            _run_with_retries(mock_func, retries=2, initial_delay_seconds=1.0, backoff_factor=2.0)
        
        # Should have been called with increasing delays
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert len(sleep_calls) == 2
        assert sleep_calls[0] == 1.0  # First retry delay
        assert sleep_calls[1] == 2.0  # Second retry delay (1.0 * 2.0)

    def test_thread_executor_configuration(self):
        """Test that thread executors are configured correctly."""
        # Test task_executor
        assert isinstance(task_executor, ThreadPoolExecutor)
        assert task_executor._max_workers == 2
        assert "mapping_task" in task_executor._thread_name_prefix
        
        # Test email_executor
        assert isinstance(email_executor, ThreadPoolExecutor)
        assert email_executor._max_workers == 5
        assert "email_task" in email_executor._thread_name_prefix

    def test_scheduler_job_intervals(self):
        """Test that scheduler jobs have correct intervals."""
        with patch('mpi_backend.background.scheduler.BackgroundScheduler') as mock_bg_scheduler:
            mock_scheduler_instance = Mock()
            mock_bg_scheduler.return_value = mock_scheduler_instance
            
            init_scheduler()
            
            job_calls = mock_scheduler_instance.add_job.call_args_list
            
            # Find email download job (every 5 minutes)
            email_job = next(
                call for call in job_calls 
                if len(call) > 1 and call[1].get('id') == 'email_download'
            )
            assert call[1]['minutes'] == 5
            
            # Find statement download job (every 12 hours)
            statement_job = next(
                call for call in job_calls 
                if len(call) > 1 and call[1].get('id') == 'statement_download'
            )
            assert call[1]['hours'] == 12

    def test_scheduler_cron_jobs(self):
        """Test that cron jobs are configured with correct timing."""
        with patch('mpi_backend.background.scheduler.BackgroundScheduler') as mock_bg_scheduler:
            with patch('mpi_backend.background.scheduler.CronTrigger') as mock_cron:
                mock_scheduler_instance = Mock()
                mock_bg_scheduler.return_value = mock_scheduler_instance
                
                init_scheduler()
                
                # Verify CronTrigger was called for cron jobs
                cron_calls = mock_cron.call_args_list
                assert len(cron_calls) >= 2  # At least 2 cron jobs
                
                # Check daily UIDI update (13:00 UTC = 6 PM PKT)
                daily_cron = next(
                    call for call in cron_calls 
                    if call[1].get('hour') == 13 and call[1].get('minute') == 0
                )
                assert daily_cron[1]['timezone'] == UTC_TZ
                
                # Check weekly mappings update (Saturday 3:00 UTC = 8 AM PKT)
                weekly_cron = next(
                    call for call in cron_calls 
                    if call[1].get('hour') == 3 and call[1].get('day_of_week') == 5
                )
                assert weekly_cron[1]['timezone'] == UTC_TZ

    def test_scheduler_error_handling_in_tasks(self):
        """Test error handling within scheduled tasks."""
        # Test email download wrapper error handling
        with patch('mpi_backend.background.scheduler.email_executor') as mock_executor:
            mock_executor.submit = Mock()
            
            async_email_download_wrapper()
            
            submitted_func = mock_executor.submit.call_args[0][0]
            
            # Test with failing download task
            with patch('mpi_backend.utils.invoice_downaloder.email_download_background_task') as mock_task:
                mock_task.side_effect = Exception("Download failed")
                
                # Should not raise exception due to _run_with_retries
                submitted_func()

    def test_scheduler_concurrency_safety(self):
        """Test that scheduler operations are thread-safe."""
        results = []
        errors = []
        
        def worker():
            try:
                # Test multiple wrapper calls
                async_email_download_wrapper()
                async_statement_download_wrapper()
                memory_cleanup_task()
                results.append("success")
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = []
        for _ in range(5):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
        
        # Wait for completion
        for t in threads:
            t.join()
        
        # All should succeed
        assert len(errors) == 0
        assert len(results) == 5

    def test_scheduler_configuration_environment_variables(self):
        """Test scheduler behavior with different environment variables."""
        # Test with mappings disabled
        with patch.dict('os.environ', {'ENABLE_MAPPINGS': 'false'}):
            with patch('mpi_backend.background.scheduler.BackgroundScheduler') as mock_bg_scheduler:
                mock_scheduler_instance = Mock()
                mock_bg_scheduler.return_value = mock_scheduler_instance
                
                # Should still create scheduler (mappings are controlled elsewhere)
                scheduler = init_scheduler()
                
                # Verify scheduler was created
                mock_bg_scheduler.assert_called_once()

    def test_scheduler_job_misfire_grace_time(self):
        """Test that jobs have appropriate misfire grace times."""
        with patch('mpi_backend.background.scheduler.BackgroundScheduler') as mock_bg_scheduler:
            mock_scheduler_instance = Mock()
            mock_bg_scheduler.return_value = mock_scheduler_instance
            
            init_scheduler()
            
            # Check job defaults
            call_args = mock_bg_scheduler.call_args
            job_defaults = call_args[1]['job_defaults']
            
            assert 'misfire_grace_time' in job_defaults
            assert job_defaults['misfire_grace_time'] == 300

    def test_scheduler_max_instances_configuration(self):
        """Test that jobs are configured with max_instances=1."""
        with patch('mpi_backend.background.scheduler.BackgroundScheduler') as mock_bg_scheduler:
            mock_scheduler_instance = Mock()
            mock_bg_scheduler.return_value = mock_scheduler_instance
            
            init_scheduler()
            
            job_calls = mock_scheduler_instance.add_job.call_args_list
            
            # All jobs should have max_instances=1
            for call in job_calls:
                if len(call) > 1:
                    assert call[1].get('max_instances') == 1

    def test_quickbooks_priority_integration(self):
        """Test QuickBooks priority control integration."""
        with patch('mpi_backend.background.scheduler.set_scheduler_instance') as mock_set_scheduler:
            with patch('mpi_backend.background.scheduler.BackgroundScheduler') as mock_bg_scheduler:
                mock_scheduler_instance = Mock()
                mock_bg_scheduler.return_value = mock_scheduler_instance
                
                scheduler = init_scheduler()
                
                # Verify scheduler was registered for QuickBooks priority control
                mock_set_scheduler.assert_called_once_with(mock_scheduler_instance)

    def test_timezone_configuration(self):
        """Test that scheduler uses correct timezone."""
        with patch('mpi_backend.background.scheduler.BackgroundScheduler') as mock_bg_scheduler:
            mock_scheduler_instance = Mock()
            mock_bg_scheduler.return_value = mock_scheduler_instance
            
            init_scheduler()
            
            # Verify UTC timezone is used
            call_args = mock_bg_scheduler.call_args
            assert call_args[1]['timezone'] == UTC_TZ
            assert UTC_TZ == pytz.utc

    def test_scheduler_job_replacement(self):
        """Test that jobs are configured to replace existing ones."""
        with patch('mpi_backend.background.scheduler.BackgroundScheduler') as mock_bg_scheduler:
            mock_scheduler_instance = Mock()
            mock_bg_scheduler.return_value = mock_scheduler_instance
            
            init_scheduler()
            
            job_calls = mock_scheduler_instance.add_job.call_args_list
            
            # All jobs should have replace_existing=True
            for call in job_calls:
                if len(call) > 1:
                    assert call[1].get('replace_existing') is True

    def test_async_wrapper_error_logging(self, caplog):
        """Test that async wrappers log errors appropriately."""
        import logging
        
        with patch('mpi_backend.background.scheduler.email_executor') as mock_executor:
            mock_executor.submit = Mock()
            
            async_email_download_wrapper()
            
            submitted_func = mock_executor.submit.call_args[0][0]
            
            # Test with failing task that logs errors
            with patch('mpi_backend.utils.invoice_downaloder.email_download_background_task') as mock_task:
                mock_task.side_effect = Exception("Test error")
                
                submitted_func()
                
                # Should have logged the start and completion (even with error)
                log_messages = [record.message for record in caplog.records]
                assert any('Starting async email download task' in msg for msg in log_messages)

    def test_resource_cleanup_and_management(self):
        """Test that resources are properly managed."""
        # Test thread executor limits
        assert task_executor._max_workers <= 5  # Reasonable limit
        assert email_executor._max_workers <= 10  # Reasonable limit
        
        # Test that executors can be used
        future1 = task_executor.submit(lambda: "test1")
        future2 = email_executor.submit(lambda: "test2")
        
        assert future1.result(timeout=1) == "test1"
        assert future2.result(timeout=1) == "test2"

    def test_scheduler_integration_with_real_components(self):
        """Test scheduler integration with real component imports."""
        # This tests that the imports in the scheduler work correctly
        
        # Test that wrapper functions can import their dependencies
        try:
            async_email_download_wrapper()
            async_statement_download_wrapper()
            async_failed_invoice_recovery_wrapper()
            async_missing_invoice_download_wrapper()
            # These should not fail due to import errors
        except ImportError:
            pytest.fail("Scheduler wrapper functions have import issues")
        except Exception:
            # Other exceptions are expected if actual tasks run
            pass
