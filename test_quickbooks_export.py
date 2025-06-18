#!/usr/bin/env python3
"""
Comprehensive QuickBooks Export Test Script

This script thoroughly tests the QuickBooks export flow for:
1. Correctness - Proper data export and status updates
2. Stability - Error handling and edge cases
3. Performance - Large dataset handling and optimization

Usage:
    python test_quickbooks_export.py
"""

import sys
import os
import time
import json
import asyncio
import logging
from datetime import datetime, date
from typing import List, Dict, Any
from uuid import uuid4, UUID

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from mpi_backend.database import SessionLocal, get_db
    from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
    from mpi_backend.database.controllers.invoice import InvoiceController
    from mpi_backend.database.controllers.ItemClassification import ItemClassificationController
    from mpi_backend.database.controllers.Suppliers import SupplierController
    from mpi_backend.database.models.InvoiceItems import InvoiceItem
    from mpi_backend.database.models.invoice import Invoice
    from mpi_backend.database.models.Suppliers import Supplier
    from mpi_backend.database.models.ItemClassification import ItemClassification
    from mpi_backend.database.schemas.Filters import SendtoQBFilterRequest
    from mpi_backend.api.routes.quickbooks import migrate_all_invoice_to_QB, migrate_invoice_to_QB
    from mpi_backend.utils.pdf_to_excel.formatting_util import export_batch_entry_to_excel
    import pandas as pd
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure you're running this from the project root and have activated the conda environment")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('quickbooks_export_test.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class QuickBooksExportTester:
    """Comprehensive QuickBooks export testing class"""
    
    def __init__(self):
        self.db = SessionLocal()
        self.invoice_controller = InvoiceController(self.db)
        self.item_controller = InvoiceItemController(self.db)
        self.classification_controller = ItemClassificationController(self.db)
        self.supplier_controller = SupplierController(self.db)
        self.test_results = {
            'tests_run': 0,
            'tests_passed': 0,
            'tests_failed': 0,
            'errors': [],
            'performance_metrics': {}
        }
    
    def log_test_result(self, test_name: str, passed: bool, details: str = "", performance_data: Dict = None):
        """Log test results"""
        self.test_results['tests_run'] += 1
        if passed:
            self.test_results['tests_passed'] += 1
            logger.info(f"✅ {test_name}: PASSED - {details}")
        else:
            self.test_results['tests_failed'] += 1
            self.test_results['errors'].append(f"{test_name}: {details}")
            logger.error(f"❌ {test_name}: FAILED - {details}")
        
        if performance_data:
            self.test_results['performance_metrics'][test_name] = performance_data
    
    def test_required_methods_exist(self):
        """Test 1: Verify all required methods exist and are callable"""
        logger.info("🧪 Testing required methods existence...")
        
        try:
            # Test InvoiceItemController methods
            assert hasattr(self.item_controller, 'get_invoice_items_by_invoice_ids'), "Missing get_invoice_items_by_invoice_ids"
            assert hasattr(self.item_controller, 'get_suppliers_by_ids'), "Missing get_suppliers_by_ids" 
            assert hasattr(self.item_controller, 'set_export_status_to_sent'), "Missing set_export_status_to_sent"
            assert hasattr(self.item_controller, 'is_exported'), "Missing is_exported"
            
            # Test InvoiceController methods
            assert hasattr(self.invoice_controller, 'get_invoices_by_ids'), "Missing get_invoices_by_ids"
            assert hasattr(self.invoice_controller, 'set_invoice_is_exported'), "Missing set_invoice_is_exported"
            
            # Test ItemClassificationController methods
            assert hasattr(self.classification_controller, 'get_all_classifications'), "Missing get_all_classifications"
            assert hasattr(self.classification_controller, 'get_classification'), "Missing get_classification"
            
            self.log_test_result("Required Methods Existence", True, "All required methods found")
            
        except AssertionError as e:
            self.log_test_result("Required Methods Existence", False, str(e))
    
    def test_data_model_integrity(self):
        """Test 2: Verify data model integrity and relationships"""
        logger.info("🧪 Testing data model integrity...")
        
        try:
            # Check if we have sample data
            sample_items = self.item_controller.get_invoice_items()
            if not sample_items:
                self.log_test_result("Data Model Integrity", False, "No sample invoice items found")
                return
            
            # Test first item for required attributes
            first_item = sample_items[0]
            required_attrs = ['id', 'invoice_id', 'vendor', 'export_status', 'item', 'description', 
                            'amount', 'date', 'ref_no', 'customer_job', 'class_', 'memo']
            
            missing_attrs = []
            for attr in required_attrs:
                if not hasattr(first_item, attr):
                    missing_attrs.append(attr)
            
            if missing_attrs:
                self.log_test_result("Data Model Integrity", False, f"Missing attributes: {missing_attrs}")
            else:
                self.log_test_result("Data Model Integrity", True, f"Verified {len(required_attrs)} required attributes")
                
        except Exception as e:
            self.log_test_result("Data Model Integrity", False, f"Exception: {str(e)}")
    
    def test_method_functionality(self):
        """Test 3: Test individual method functionality"""
        logger.info("🧪 Testing method functionality...")
        
        try:
            # Test get_invoice_items_by_invoice_ids with sample data
            sample_items = self.item_controller.get_invoice_items()[:5]  # Get first 5 items
            if not sample_items:
                self.log_test_result("Method Functionality", False, "No sample data available")
                return
            
            # Get unique invoice IDs
            invoice_ids = list(set([item.invoice_id for item in sample_items]))
            
            # Test the method
            start_time = time.time()
            retrieved_items = self.item_controller.get_invoice_items_by_invoice_ids(invoice_ids)
            execution_time = time.time() - start_time
            
            if retrieved_items:
                performance_data = {
                    'execution_time': execution_time,
                    'items_retrieved': len(retrieved_items),
                    'invoices_queried': len(invoice_ids)
                }
                self.log_test_result("Method Functionality", True, 
                                   f"Retrieved {len(retrieved_items)} items in {execution_time:.3f}s", 
                                   performance_data)
            else:
                self.log_test_result("Method Functionality", False, "No items retrieved")
                
        except Exception as e:
            self.log_test_result("Method Functionality", False, f"Exception: {str(e)}")
    
    def test_classification_functionality(self):
        """Test 4: Test classification functionality"""
        logger.info("🧪 Testing classification functionality...")
        
        try:
            # Test get_all_classifications
            classifications = self.classification_controller.get_all_classifications()
            
            # Test get_classification with sample items
            test_items = ["pipe", "valve", "fitting", "nonexistent_item_xyz123"]
            classification_results = []
            
            for item in test_items:
                classification = self.classification_controller.get_classification(item)
                classification_results.append(f"{item}: {classification}")
            
            self.log_test_result("Classification Functionality", True, 
                               f"Classifications retrieved: {len(classifications)}, Test results: {classification_results}")
            
        except Exception as e:
            self.log_test_result("Classification Functionality", False, f"Exception: {str(e)}")
    
    def test_export_data_structure(self):
        """Test 5: Test export data structure and Excel generation"""
        logger.info("🧪 Testing export data structure...")
        
        try:
            # Create sample export data
            sample_data = [
                {
                    "Date": datetime.now().date(),
                    "Ref": "TEST001",
                    "vendor": "Test Supplier",
                    "terms": "Due on receipt",
                    "bill due": datetime.now().date(),
                    "account": "Purchases - Cost of Goods Sold",
                    "Amount": "100.00",
                    "Memo": "Test item description",
                    "Customer Job": "Test Job",
                    "Class": "Test Class"
                }
            ]
            
            # Test DataFrame creation and Excel export
            df = pd.DataFrame(sample_data)
            
            start_time = time.time()
            export_path = export_batch_entry_to_excel(df)
            export_time = time.time() - start_time
            
            # Verify file exists
            file_exists = os.path.exists(export_path)
            file_size = os.path.getsize(export_path) if file_exists else 0
            
            if file_exists:
                # Clean up test file
                os.remove(export_path)
                
                performance_data = {
                    'export_time': export_time,
                    'file_size_bytes': file_size,
                    'records_exported': len(sample_data)
                }
                self.log_test_result("Export Data Structure", True, 
                                   f"Excel file created in {export_time:.3f}s, size: {file_size} bytes", 
                                   performance_data)
            else:
                self.log_test_result("Export Data Structure", False, "Excel file not created")
                
        except Exception as e:
            self.log_test_result("Export Data Structure", False, f"Exception: {str(e)}")
    
    def test_status_updates(self):
        """Test 6: Test status update functionality"""
        logger.info("🧪 Testing status update functionality...")
        
        try:
            # Get sample items with "Pending" status
            sample_items = [item for item in self.item_controller.get_invoice_items() if item.export_status == "Pending"][:3]
            
            if not sample_items:
                self.log_test_result("Status Updates", False, "No items with 'Pending' status found")
                return
            
            item_ids = [item.id for item in sample_items]
            
            # Test status update
            start_time = time.time()
            updated_count = self.item_controller.set_export_status_to_sent(item_ids)
            update_time = time.time() - start_time
            
            # Verify updates
            verification_items = self.item_controller.get_invoice_items_by_ids(item_ids)
            sent_count = sum(1 for item in verification_items if item.export_status == "Sent")
            
            # Revert changes for next tests
            self.db.query(InvoiceItem).filter(InvoiceItem.id.in_(item_ids)).update(
                {"export_status": "Pending"}, synchronize_session='fetch'
            )
            self.db.commit()
            
            performance_data = {
                'update_time': update_time,
                'items_updated': updated_count,
                'verified_sent': sent_count
            }
            
            if updated_count == len(item_ids) and sent_count == len(item_ids):
                self.log_test_result("Status Updates", True, 
                                   f"Updated {updated_count} items in {update_time:.3f}s", 
                                   performance_data)
            else:
                self.log_test_result("Status Updates", False, 
                                   f"Expected {len(item_ids)} updates, got {updated_count}, verified {sent_count}")
                
        except Exception as e:
            self.log_test_result("Status Updates", False, f"Exception: {str(e)}")
    
    def test_performance_large_dataset(self):
        """Test 7: Test performance with large dataset simulation"""
        logger.info("🧪 Testing performance with large dataset...")
        
        try:
            # Get all available invoice items
            all_items = self.item_controller.get_invoice_items()
            
            if len(all_items) < 10:
                self.log_test_result("Performance Large Dataset", False, 
                                   f"Insufficient data for performance test (only {len(all_items)} items)")
                return
            
            # Test with different batch sizes
            test_sizes = [min(10, len(all_items)), min(100, len(all_items)), min(1000, len(all_items))]
            performance_results = []
            
            for test_size in test_sizes:
                test_items = all_items[:test_size]
                invoice_ids = list(set([item.invoice_id for item in test_items]))
                
                start_time = time.time()
                retrieved_items = self.item_controller.get_invoice_items_by_invoice_ids(invoice_ids)
                execution_time = time.time() - start_time
                
                performance_results.append({
                    'test_size': test_size,
                    'execution_time': execution_time,
                    'items_per_second': test_size / execution_time if execution_time > 0 else 0
                })
            
            # Verify performance is reasonable (arbitrary threshold)
            avg_items_per_second = sum(r['items_per_second'] for r in performance_results) / len(performance_results)
            
            performance_data = {
                'performance_results': performance_results,
                'avg_items_per_second': avg_items_per_second
            }
            
            if avg_items_per_second > 100:  # Threshold: at least 100 items per second
                self.log_test_result("Performance Large Dataset", True, 
                                   f"Average {avg_items_per_second:.1f} items/sec", 
                                   performance_data)
            else:
                self.log_test_result("Performance Large Dataset", False, 
                                   f"Performance below threshold: {avg_items_per_second:.1f} items/sec")
                
        except Exception as e:
            self.log_test_result("Performance Large Dataset", False, f"Exception: {str(e)}")
    
    def test_error_handling(self):
        """Test 8: Test error handling and edge cases"""
        logger.info("🧪 Testing error handling...")
        
        try:
            error_tests = []
            
            # Test 1: Empty invoice IDs list
            try:
                result = self.item_controller.get_invoice_items_by_invoice_ids([])
                error_tests.append(("Empty invoice IDs", len(result) == 0))
            except Exception as e:
                error_tests.append(("Empty invoice IDs", False, str(e)))
            
            # Test 2: Invalid invoice IDs
            try:
                invalid_ids = [str(uuid4()), str(uuid4())]
                result = self.item_controller.get_invoice_items_by_invoice_ids(invalid_ids)
                error_tests.append(("Invalid invoice IDs", len(result) == 0))
            except Exception as e:
                error_tests.append(("Invalid invoice IDs", False, str(e)))
            
            # Test 3: Empty item IDs for status update
            try:
                result = self.item_controller.set_export_status_to_sent([])
                error_tests.append(("Empty status update", result == 0))
            except Exception as e:
                error_tests.append(("Empty status update", False, str(e)))
            
            # Test 4: Invalid item IDs for status update
            try:
                result = self.item_controller.set_export_status_to_sent([99999999, 99999998])
                error_tests.append(("Invalid item IDs", result == 0))
            except Exception as e:
                error_tests.append(("Invalid item IDs", False, str(e)))
            
            passed_tests = sum(1 for test in error_tests if len(test) == 2 and test[1])
            total_tests = len(error_tests)
            
            details = f"Passed {passed_tests}/{total_tests} error handling tests"
            for test in error_tests:
                if len(test) > 2:  # Has error
                    details += f"\n  {test[0]}: {test[2]}"
            
            self.log_test_result("Error Handling", passed_tests == total_tests, details)
            
        except Exception as e:
            self.log_test_result("Error Handling", False, f"Exception: {str(e)}")
    
    def test_end_to_end_flow(self):
        """Test 9: End-to-end QuickBooks export flow simulation"""
        logger.info("🧪 Testing end-to-end export flow...")
        
        try:
            # Get sample data
            sample_items = self.item_controller.get_invoice_items()[:5]
            if not sample_items:
                self.log_test_result("End-to-End Flow", False, "No sample data available")
                return
            
            invoice_ids = list(set([UUID(str(item.invoice_id)) for item in sample_items]))
            
            # Simulate the export process step by step
            start_time = time.time()
            
            # Step 1: Get invoice items
            invoice_items = self.item_controller.get_invoice_items_by_invoice_ids(invoice_ids)
            step1_time = time.time()
            
            # Step 2: Get vendor names
            vendor_names = list(set([item.vendor for item in invoice_items if item.vendor]))
            
            # Step 3: Get invoices
            invoices = self.invoice_controller.get_invoices_by_ids(invoice_ids)
            invoices_dict = {invoice.id: invoice for invoice in invoices}
            step2_time = time.time()
            
            # Step 4: Process items and create export data
            batch_entries = []
            item_ids_to_update = []
            
            for item in invoice_items:
                try:
                    # Get classification
                    classification = self.classification_controller.get_classification(
                        item.description or item.item or ""
                    )
                    
                    # Get invoice details
                    invoice = invoices_dict.get(item.invoice_id)
                    invoice_date = invoice.date if invoice else item.date
                    
                    # Build batch entry
                    batch_entry = {
                        "Date": invoice_date,
                        "Ref": item.ref_no,
                        "vendor": item.vendor or "Unknown Supplier",
                        "terms": "Due on receipt",
                        "bill due": invoice_date,
                        "account": classification or "Purchases - Cost of Goods Sold",
                        "Amount": item.amount,
                        "Memo": item.description or item.item or "",
                        "Customer Job": item.customer_job or "",
                        "Class": item.class_ or ""
                    }
                    
                    batch_entries.append(batch_entry)
                    item_ids_to_update.append(item.id)
                    
                except Exception as e:
                    logger.warning(f"Error processing item {item.id}: {e}")
                    continue
            
            step3_time = time.time()
            
            # Step 5: Create DataFrame and export to Excel
            if batch_entries:
                df = pd.DataFrame(batch_entries)
                export_path = export_batch_entry_to_excel(df)
                
                # Verify file exists and clean up
                file_exists = os.path.exists(export_path)
                if file_exists:
                    file_size = os.path.getsize(export_path)
                    os.remove(export_path)
                else:
                    file_size = 0
            else:
                file_exists = False
                file_size = 0
            
            step4_time = time.time()
            
            # Performance metrics
            performance_data = {
                'total_time': step4_time - start_time,
                'step1_get_items': step1_time - start_time,
                'step2_get_invoices': step2_time - step1_time,
                'step3_process_data': step3_time - step2_time,
                'step4_export_excel': step4_time - step3_time,
                'items_processed': len(batch_entries),
                'invoices_processed': len(invoice_ids),
                'file_size_bytes': file_size
            }
            
            success = (
                len(invoice_items) > 0 and
                len(batch_entries) > 0 and
                file_exists
            )
            
            details = (f"Processed {len(batch_entries)} items from {len(invoice_ids)} invoices "
                      f"in {performance_data['total_time']:.3f}s, exported {file_size} bytes")
            
            self.log_test_result("End-to-End Flow", success, details, performance_data)
            
        except Exception as e:
            self.log_test_result("End-to-End Flow", False, f"Exception: {str(e)}")
    
    def run_all_tests(self):
        """Run all tests"""
        logger.info("🚀 Starting comprehensive QuickBooks export tests...")
        
        test_methods = [
            self.test_required_methods_exist,
            self.test_data_model_integrity,
            self.test_method_functionality,
            self.test_classification_functionality,
            self.test_export_data_structure,
            self.test_status_updates,
            self.test_performance_large_dataset,
            self.test_error_handling,
            self.test_end_to_end_flow
        ]
        
        for test_method in test_methods:
            try:
                test_method()
            except Exception as e:
                logger.error(f"Critical error in {test_method.__name__}: {e}")
                self.test_results['tests_run'] += 1
                self.test_results['tests_failed'] += 1
                self.test_results['errors'].append(f"{test_method.__name__}: Critical error - {str(e)}")
    
    def generate_report(self):
        """Generate comprehensive test report"""
        logger.info("📊 Generating test report...")
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total_tests': self.test_results['tests_run'],
                'passed': self.test_results['tests_passed'],
                'failed': self.test_results['tests_failed'],
                'success_rate': f"{(self.test_results['tests_passed'] / self.test_results['tests_run'] * 100):.1f}%" if self.test_results['tests_run'] > 0 else "0%"
            },
            'errors': self.test_results['errors'],
            'performance_metrics': self.test_results['performance_metrics']
        }
        
        # Save report to file
        with open('quickbooks_export_test_report.json', 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        # Print summary
        print("\n" + "="*80)
        print("🏁 QUICKBOOKS EXPORT TEST RESULTS")
        print("="*80)
        print(f"Total Tests: {report['summary']['total_tests']}")
        print(f"Passed: {report['summary']['passed']}")
        print(f"Failed: {report['summary']['failed']}")
        print(f"Success Rate: {report['summary']['success_rate']}")
        
        if report['errors']:
            print(f"\n❌ ERRORS ({len(report['errors'])}):")
            for error in report['errors']:
                print(f"  - {error}")
        
        if report['performance_metrics']:
            print(f"\n📈 PERFORMANCE METRICS:")
            for test_name, metrics in report['performance_metrics'].items():
                print(f"  {test_name}:")
                for metric, value in metrics.items():
                    if isinstance(value, float):
                        print(f"    {metric}: {value:.3f}")
                    else:
                        print(f"    {metric}: {value}")
        
        print(f"\n📄 Detailed report saved to: quickbooks_export_test_report.json")
        print("="*80)
        
        return report
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            self.db.close()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

def main():
    """Main test execution function"""
    tester = QuickBooksExportTester()
    
    try:
        tester.run_all_tests()
        report = tester.generate_report()
        
        # Exit with non-zero code if any tests failed
        exit_code = 0 if report['summary']['failed'] == 0 else 1
        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        logger.info("Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Critical error during testing: {e}")
        sys.exit(1)
    finally:
        tester.cleanup()

if __name__ == "__main__":
    main() 