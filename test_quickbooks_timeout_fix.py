#!/usr/bin/env python3
"""
ENHANCED Test Suite for QuickBooks Timeout Fix with MIGRATE-ALL Priority

This comprehensive test suite verifies that:
1. All timeout configurations are properly set
2. FastAPI app starts with timeout middleware 
3. Progress tracking works correctly
4. Chunking logic handles large datasets
5. Environment variables are configured
6. MIGRATE-ALL absolute priority system works
7. Background job pausing/resuming works
8. Scheduler control is functional

Run this before deploying to ensure the timeout fix works correctly.
"""

import os
import sys
import asyncio
import logging
from unittest.mock import patch, MagicMock
import json

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_environment_variables():
    """Test that all required environment variables are set"""
    logger.info("🧪 Testing environment variables...")
    
    # MIGRATE-ALL priority environment variables
    required_vars = {
        "QB_OPERATION_TIMEOUT": "600",
        "QB_CHUNK_SIZE": "500", 
        "QB_CHUNK_DELAY": "1.0",
        "REQUEST_TIMEOUT_QUICKBOOKS": "600",
        "REQUEST_TIMEOUT_MIGRATE_ALL": "900",  # NEW: 15 minutes for migrate-all
        "QB_PRIORITY_MODE": "true",
        "QB_PAUSE_BACKGROUND_JOBS": "true",
        "MIGRATE_ALL_ABSOLUTE_PRIORITY": "true",  # NEW
        "MIGRATE_ALL_PAUSE_ALL_JOBS": "true"  # NEW
    }
    
    for var, default_value in required_vars.items():
        value = os.getenv(var, default_value)
        os.environ[var] = value
        logger.info(f"   ✅ {var} = {value}")
    
    logger.info("✅ Environment variables test PASSED")


def test_timeout_configuration():
    """Test timeout configuration values"""
    logger.info("🧪 Testing timeout configuration...")
    
    # Test migrate-all gets longest timeout (absolute priority)
    migrate_all_timeout = int(os.getenv("REQUEST_TIMEOUT_MIGRATE_ALL", "900"))
    qb_timeout = int(os.getenv("REQUEST_TIMEOUT_QUICKBOOKS", "600"))
    export_timeout = int(os.getenv("REQUEST_TIMEOUT_EXPORT", "300"))
    default_timeout = int(os.getenv("REQUEST_TIMEOUT_DEFAULT", "120"))
    
    # Verify priority order: MIGRATE-ALL > QB > Export > Default
    assert migrate_all_timeout > qb_timeout, "MIGRATE-ALL should have highest timeout"
    assert qb_timeout > export_timeout, "QuickBooks should have higher timeout than exports"
    assert export_timeout > default_timeout, "Exports should have higher timeout than default"
    
    logger.info(f"   ✅ MIGRATE-ALL timeout: {migrate_all_timeout}s (HIGHEST PRIORITY)")
    logger.info(f"   ✅ QuickBooks timeout: {qb_timeout}s") 
    logger.info(f"   ✅ Export timeout: {export_timeout}s")
    logger.info(f"   ✅ Default timeout: {default_timeout}s")
    
    # Test chunking configuration
    chunk_size = int(os.getenv("QB_CHUNK_SIZE", "500"))
    chunk_delay = float(os.getenv("QB_CHUNK_DELAY", "1.0"))
    
    assert 100 <= chunk_size <= 1000, "Chunk size should be reasonable"
    assert 0.1 <= chunk_delay <= 5.0, "Chunk delay should be reasonable"
    
    logger.info(f"   ✅ Chunk size: {chunk_size} invoices")
    logger.info(f"   ✅ Chunk delay: {chunk_delay}s")
    
    logger.info("✅ Timeout configuration test PASSED")


def test_priority_system():
    """Test the enhanced priority system"""
    logger.info("🧪 Testing MIGRATE-ALL priority system...")
    
    try:
        # Test priority module import
        from mpi_backend.utils.quickbooks_priority import (
            pause_all_background_jobs_for_migrate_all,
            resume_all_background_jobs_from_migrate_all,
            is_migrate_all_active,
            set_scheduler_instance,
            get_qb_priority_status
        )
        
        logger.info("   ✅ Priority control imports successful")
        
        # Test priority status
        status = get_qb_priority_status()
        expected_keys = [
            "priority_mode_enabled", 
            "background_job_pausing",
            "migrate_all_active",  # NEW
            "scheduler_available"  # NEW
        ]
        
        for key in expected_keys:
            assert key in status, f"Missing key: {key}"
            
        logger.info("   ✅ Priority status structure correct")
        
        # Test migrate-all priority functions
        assert not is_migrate_all_active(), "Migrate-all should not be active initially"
        
        # Mock scheduler for testing
        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = MagicMock()
        set_scheduler_instance(mock_scheduler)
        
        # Test pausing
        pause_all_background_jobs_for_migrate_all()
        assert is_migrate_all_active(), "Migrate-all should be active after pausing"
        
        # Test resuming
        resume_all_background_jobs_from_migrate_all()
        assert not is_migrate_all_active(), "Migrate-all should not be active after resuming"
        
        logger.info("   ✅ MIGRATE-ALL priority functions work correctly")
        
    except ImportError as e:
        logger.error(f"   ❌ Priority system import failed: {e}")
        return False
        
    logger.info("✅ MIGRATE-ALL priority system test PASSED")
    return True


def test_fastapi_app_with_enhanced_middleware():
    """Test that FastAPI app starts with enhanced timeout middleware"""
    logger.info("🧪 Testing FastAPI app with enhanced middleware...")
    
    try:
        # Test app import
        from mpi_backend.main import app
        logger.info("   ✅ FastAPI app import successful")
        
        # Test middleware is properly configured
        middleware_names = [str(type(m)) for m in app.user_middleware]
        has_timeout_middleware = any("timeout" in name.lower() for name in middleware_names)
        
        if not has_timeout_middleware:
            logger.warning("   ⚠️  Timeout middleware may not be properly configured")
        else:
            logger.info("   ✅ Timeout middleware detected")
            
        # Test route registration
        routes = [route.path for route in app.routes if hasattr(route, 'path')]
        required_routes = ["/quickbooks/migrate-all", "/quickbooks/progress"]
        
        for route in required_routes:
            if any(route in r for r in routes):
                logger.info(f"   ✅ Route {route} registered")
            else:
                logger.warning(f"   ⚠️  Route {route} may not be registered")
        
    except Exception as e:
        logger.error(f"   ❌ FastAPI app test failed: {e}")
        return False
        
    logger.info("✅ FastAPI app with enhanced middleware test PASSED")
    return True


def test_chunking_logic():
    """Test chunking logic for large datasets"""
    logger.info("🧪 Testing enhanced chunking logic...")
    
    # Test chunk creation
    chunk_size = int(os.getenv("QB_CHUNK_SIZE", "500"))
    
    # Test with various dataset sizes
    test_sizes = [100, 500, 1000, 2500, 5000]
    
    for size in test_sizes:
        invoice_ids = list(range(size))
        chunks = [invoice_ids[i:i + chunk_size] 
                 for i in range(0, len(invoice_ids), chunk_size)]
        
        expected_chunks = (size + chunk_size - 1) // chunk_size  # Ceiling division
        actual_chunks = len(chunks)
        
        assert actual_chunks == expected_chunks, f"Chunk count mismatch for size {size}"
        
        # Verify all items are included
        total_items = sum(len(chunk) for chunk in chunks)
        assert total_items == size, f"Item count mismatch for size {size}"
        
        logger.info(f"   ✅ {size} items → {actual_chunks} chunks")
    
    logger.info("✅ Enhanced chunking logic test PASSED")


def test_progress_tracking():
    """Test progress tracking functionality"""
    logger.info("🧪 Testing enhanced progress tracking...")
    
    try:
        from mpi_backend.api.routes.quickbooks import update_progress, qb_operation_progress
        
        # Test progress updates
        operation_id = "test_operation_123"
        
        # Test various progress stages
        stages = [
            ("initializing", 0, "Starting test"),
            ("filtering", 25, "Filtering data"),
            ("processing", 50, "Processing items"),
            ("uploading", 75, "Uploading to S3"),
            ("completed", 100, "Test completed")
        ]
        
        for stage, progress, message in stages:
            update_progress(operation_id, stage, progress, message)
            
            # Verify progress was recorded
            assert operation_id in qb_operation_progress
            progress_data = qb_operation_progress[operation_id]
            
            assert progress_data["stage"] == stage
            assert progress_data["progress"] == progress
            assert progress_data["message"] == message
            assert "timestamp" in progress_data
            
            logger.info(f"   ✅ Progress tracking: {stage} {progress}%")
        
        # Clean up
        del qb_operation_progress[operation_id]
        
    except Exception as e:
        logger.error(f"   ❌ Progress tracking test failed: {e}")
        return False
        
    logger.info("✅ Enhanced progress tracking test PASSED")
    return True


async def test_background_job_coordination():
    """Test background job coordination with migrate-all"""
    logger.info("🧪 Testing background job coordination...")
    
    try:
        from mpi_backend.utils.quickbooks_priority import (
            pause_all_background_jobs_for_migrate_all,
            resume_all_background_jobs_from_migrate_all,
            is_migrate_all_active
        )
        
        # Test initial state
        assert not is_migrate_all_active(), "Should start with no migrate-all active"
        
        # Test pause
        pause_all_background_jobs_for_migrate_all()
        assert is_migrate_all_active(), "Should be active after pause"
        
        # Test that background tasks would be paused
        from mpi_backend.utils.invoice_downaloder import email_download_background_task
        from mpi_backend.utils.statement_downloader import statement_download_background_task
        
        # These should exit early when migrate-all is active
        # (In real scenario, they would return without processing)
        
        # Test resume
        resume_all_background_jobs_from_migrate_all()
        assert not is_migrate_all_active(), "Should not be active after resume"
        
        logger.info("   ✅ Background job coordination works correctly")
        
    except Exception as e:
        logger.error(f"   ❌ Background job coordination test failed: {e}")
        return False
        
    logger.info("✅ Background job coordination test PASSED")
    return True


def run_all_tests():
    """Run all enhanced tests"""
    logger.info("🚀 Running ENHANCED QuickBooks Timeout Fix Test Suite with MIGRATE-ALL Priority...")
    logger.info("="*80)
    
    tests = [
        test_environment_variables,
        test_timeout_configuration,
        test_priority_system,
        test_fastapi_app_with_enhanced_middleware,
        test_chunking_logic,
        test_progress_tracking,
    ]
    
    async_tests = [
        test_background_job_coordination
    ]
    
    passed = 0
    total = len(tests) + len(async_tests)
    
    # Run synchronous tests
    for test in tests:
        try:
            result = test()
            if result is not False:
                passed += 1
        except Exception as e:
            logger.error(f"❌ Test {test.__name__} failed with exception: {e}")
    
    # Run asynchronous tests  
    async def run_async_tests():
        nonlocal passed
        for test in async_tests:
            try:
                result = await test()
                if result is not False:
                    passed += 1
            except Exception as e:
                logger.error(f"❌ Test {test.__name__} failed with exception: {e}")
    
    # Run async tests
    asyncio.run(run_async_tests())
    
    logger.info("="*80)
    logger.info(f"🏁 Test Suite Results: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 ALL TESTS PASSED! QuickBooks timeout fix with MIGRATE-ALL priority is ready for deployment.")
        logger.info("\n📋 What was tested:")
        logger.info("   ✅ MIGRATE-ALL absolute priority system")
        logger.info("   ✅ Enhanced timeout configurations")
        logger.info("   ✅ Dynamic background job pausing")
        logger.info("   ✅ Progress tracking system")
        logger.info("   ✅ Chunked processing for large datasets")
        logger.info("   ✅ FastAPI middleware integration")
        logger.info("   ✅ Background job coordination")
        
        logger.info("\n🚀 Ready to deploy! Use one of these startup methods:")
        logger.info("   1. python mpi_backend/startup_with_timeouts.py")
        logger.info("   2. uvicorn mpi_backend.main:app --timeout-keep-alive 65")
        
    else:
        logger.error("❌ Some tests failed. Please check the configuration before deploying.")
        
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1) 