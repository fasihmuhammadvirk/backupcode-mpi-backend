# PDF to Excel Conversion Test Suite

This directory contains a comprehensive testing framework for the PDF to Excel conversion functionality. The test suite automatically discovers suppliers and validates the entire conversion pipeline.

## 📁 Directory Structure

```
tests/pdf_to_excel_test_files/
├── bmw/
│   ├── bmw_sample_001.pdf
│   ├── bmw_sample_001_expected.xlsx
│   ├── bmw_sample_002.pdf
│   ├── bmw_sample_002_expected.xlsx
│   └── ...
├── supreme/
│   ├── supreme_sample_001.pdf
│   ├── supreme_sample_001_expected.xlsx
│   └── ...
├── af_supply/
│   ├── af_sample_001.pdf
│   ├── af_sample_001_expected.xlsx
│   └── ...
└── ...
```

## 🎯 Test Coverage

The test suite validates three critical aspects:

### ✅ 1. Functionality Check
- Ensures the PDF to Excel conversion runs without errors
- Validates error handling and fallback mechanisms
- Tests supplier-specific conversion logic

### ✅ 2. File Generation Check  
- Verifies that Excel files are created for each PDF input
- Ensures output files are in the correct format (.xlsx)
- Validates file system operations

### ✅ 3. Data Integrity Check
- Compares generated Excel files with expected outputs cell by cell
- Validates column headers, data types, and content accuracy
- Provides detailed mismatch reporting for debugging

## 🔧 Test Framework Features

### Automatic Supplier Discovery
- Tests automatically discover all suppliers in the test directory
- New suppliers can be added without modifying test code
- Supports dynamic test case generation

### Robust Error Handling
- Graceful handling of PDF conversion failures
- Fallback to test data generation for framework validation
- Detailed error reporting with context

### Comprehensive Validation
- Cell-by-cell Excel comparison
- Normalized data comparison (handles whitespace, data types)
- Limited output for readability (first 20 mismatches)

## 🚀 Running the Tests

### Run All Tests
```bash
cd /path/to/mpi-backend
python -m pytest mpi_backend/tests/test_pdf_to_excel.py -v
```

### Run Specific Test Categories
```bash
# Test supplier discovery only
python -m pytest mpi_backend/tests/test_pdf_to_excel.py::test_supplier_discovery -v

# Test specific supplier
python -m pytest mpi_backend/tests/test_pdf_to_excel.py -k "bmw" -v

# Test with detailed output
python -m pytest mpi_backend/tests/test_pdf_to_excel.py -v -s
```

## 📊 Test Results Analysis

### Successful Test Output
```
✓ PDF to Excel conversion pipeline is working
✓ Excel file generated: /path/to/output.xlsx
✓ Content validation passed for invoice.pdf
```

### Error Analysis
The framework provides detailed error context:
- Supplier name and folder
- Input PDF path
- Expected Excel path  
- Actual Excel path
- Specific error details

### Content Comparison Failures
```
Cell mismatch at row 2, column 'Description': expected 'Pipe Joint' but got 'Test Item'
Cell mismatch at row 2, column 'Amount': expected '$62.50' but got '$10.00'
```

## 🛠️ Adding New Test Data

### Step 1: Create Supplier Directory
```bash
mkdir mpi_backend/tests/pdf_to_excel_test_files/new_supplier
```

### Step 2: Add Sample PDFs
Place representative invoice PDFs in the supplier directory:
- At least 3 different invoices per supplier
- Use descriptive filenames (e.g., `supplier_invoice_001.pdf`)

### Step 3: Generate Expected Excel Files
Run the production conversion code to generate expected outputs:
```bash
# Use the setup script (recommended)
python scripts/create_sample_test_data.py

# Or manually for each PDF
python -c "
from mpi_backend.utils.pdf_to_excel.main_extractor import extract_data
extract_data('input.pdf', 'expected_output.xlsx', 'Supplier Name')
"
```

### Step 4: Update Supplier Mapping
Add the new supplier to `SUPPLIER_NAME_MAP` in `test_pdf_to_excel.py`:
```python
SUPPLIER_NAME_MAP = {
    # ... existing mappings ...
    "new_supplier": "New Supplier Full Name",
}
```

## 🔍 Test Configuration

### Supplier Name Mapping
The test framework maps folder names to full supplier names:
```python
SUPPLIER_NAME_MAP = {
    "bmw": "BMW Plumbing Supplies",
    "supreme": "Supreme Plumbing Supply",
    "af_supply": "AF Supply",
    # Add new suppliers here
}
```

### Data Normalization
The comparison logic normalizes data for accurate testing:
- Fills NaN values with empty strings
- Converts all values to strings
- Strips whitespace
- Handles different data types consistently

## 📋 Test Validation Rules

### Required Files
- Each PDF must have a corresponding `_expected.xlsx` file
- Expected files must contain valid Excel data
- Column headers must match the production schema

### Expected Excel Schema
```
Item | Description | Qty | Cost | Amount | Date | Ref NO | PO # | Customer Job | Bill | Vendor | Class | Memo | Buyer
```

### Data Quality Requirements
- All monetary values should be consistently formatted
- Dates should follow standard format (MM/DD/YYYY)
- Item codes should be properly extracted
- Customer job information should be complete

## 🐛 Troubleshooting

### Common Issues

#### PDF Conversion Failures
- **Issue**: `PdfFileReader is deprecated` errors
- **Solution**: Update PyPDF2 compatibility code in conversion utilities

#### Missing Expected Files
- **Issue**: `Missing expected Excel files` error
- **Solution**: Run `python scripts/create_sample_test_data.py` to generate missing files

#### Cell Comparison Failures
- **Issue**: Content mismatches between generated and expected Excel
- **Solution**: Review conversion logic for specific supplier or regenerate expected files

#### Library Dependencies
- **Issue**: `No module named 'jpype'` warnings
- **Solution**: Install missing dependencies or use fallback mode

### Debug Mode
Run tests with verbose output for detailed debugging:
```bash
python -m pytest mpi_backend/tests/test_pdf_to_excel.py -v -s --tb=long
```

## 🔄 Maintenance

### Regular Updates
1. **Monthly**: Verify all tests pass with latest data
2. **After code changes**: Run full test suite
3. **New supplier onboarding**: Add test data and update mappings
4. **Production issues**: Add regression test cases

### Performance Monitoring
- Track test execution time
- Monitor conversion success rates
- Identify slow-performing suppliers

### Data Refresh
Periodically refresh test data with recent production samples:
```bash
python scripts/setup_pdf_to_excel_tests.py  # Fetch from database
python scripts/create_sample_test_data.py   # Create samples
```

## 📈 Metrics and Reporting

The test framework provides comprehensive metrics:
- **Supplier Coverage**: Number of suppliers with test data
- **Test Case Count**: Total PDF/Excel pairs tested
- **Success Rate**: Percentage of passing tests
- **Error Categories**: Types of failures encountered

## 🎓 Best Practices

1. **Comprehensive Coverage**: Test at least 3 invoices per supplier
2. **Representative Data**: Use real-world invoice samples
3. **Regular Updates**: Keep test data current with production
4. **Clear Documentation**: Document any supplier-specific requirements
5. **Error Handling**: Test both success and failure scenarios
6. **Performance**: Monitor test execution time and optimize as needed

---

This testing framework ensures the reliability and accuracy of the PDF to Excel conversion pipeline, providing confidence in production deployments and facilitating rapid development cycles.
