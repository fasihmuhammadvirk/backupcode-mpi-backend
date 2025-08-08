# MPI Backend Test Suite

This directory contains comprehensive tests for the MPI Backend API, including unit tests, integration tests, performance benchmarks, and load testing.

## Quick Start

### Prerequisites
```bash
# Install test dependencies
pip install -r requirements.txt

# Ensure database is migrated (if not already done)
alembic upgrade head
```

### Run All Tests
```bash
# Run all tests with coverage
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest mpi_backend/tests/test_filters.py
```

## Running All Tests at Once

### 🚀 Quick Commands

#### **Run All Tests (Recommended)**
```bash
# From the project root directory
pytest
```

#### **Alternative: Use the helper script**
```bash
# Use the run_tests.py script (handles Python path automatically)
python run_tests.py

# With additional arguments
python run_tests.py -v --cov=mpi_backend
```

#### **Run All Tests with Coverage**
```bash
# Shows coverage report in terminal
pytest --cov=mpi_backend --cov-report=term-missing

# Generates HTML coverage report
pytest --cov=mpi_backend --cov-report=html
```

#### **Run All Tests Verbosely**
```bash
# See detailed output for each test
pytest -v

# Even more verbose (shows print statements)
pytest -v -s
```

### 📊 Different Test Categories

#### **Unit Tests Only (Fast)**
```bash
# Run only the mocked unit tests
pytest -k "not benchmark"
```

#### **Performance Tests Only**
```bash
# Run only benchmark tests
pytest -k "benchmark" --benchmark-only
```

#### **All Tests Including Benchmarks**
```bash
# Run everything including performance tests
pytest --benchmark-only
```

### ⚡ Advanced Options

#### **Run Tests in Parallel**
```bash
# Install pytest-xdist first: pip install pytest-xdist
pytest -n auto
```

#### **Run Tests with Specific Markers**
```bash
# Run only smoke tests
pytest -m "smoke"

# Run only integration tests
pytest -m "integration"
```

#### **Generate Test Report**
```bash
# Install pytest-html first: pip install pytest-html
pytest --html=report.html --self-contained-html
```

### 📁 From Different Directories

#### **From Project Root**
```bash
cd /Users/fasihmuhammadvirk/Desktop/Neural\ Lines/mpi-backend
pytest
```

#### **From Tests Directory**
```bash
cd mpi_backend/tests
pytest
```

#### **With Python Path Set**
```bash
export PYTHONPATH=$PYTHONPATH:$(pwd)
pytest
```

### 🎯 What Each Command Does

| Command | What it runs | Output |
|---------|-------------|---------|
| `pytest` | All discovered tests | Basic pass/fail |
| `pytest -v` | All tests | Verbose with test names |
| `pytest --cov=mpi_backend` | All tests + coverage | Coverage report |
| `pytest -k "benchmark"` | Only benchmark tests | Performance metrics |
| `pytest --collect-only` | No execution | Lists all tests |

### ⚡ Quick Start for You

Since you're in the project directory, simply run:

```bash
# Basic test run
pytest

# Or with coverage (recommended)
pytest --cov=mpi_backend --cov-report=term-missing

# Or use the helper script (recommended if you get import errors)
python run_tests.py
```

This will run all the tests we created:
- ✅ Health endpoint tests
- ✅ Authentication tests  
- ✅ Filter validation tests
- ✅ Invoice operation tests
- ✅ Statement endpoint tests
- ✅ QuickBooks router tests
- ✅ File upload tests
- ✅ Performance benchmarks

The tests use mocked controllers, so they don't require a real database connection and should run quickly!

## Test Categories

### 1. Unit Tests (Mocked)
- **Health Check**: `/health` endpoint
- **Authentication**: JWT bypass validation
- **Filters**: Empty requests, validation errors
- **Invoices**: Pagination, download endpoints
- **Statements**: Basic endpoint validation
- **QuickBooks**: Router presence checks

### 2. Integration Tests (Database)
- **Filter Endpoints**: Complex filtering with real data
- **Invoice Operations**: CRUD operations
- **Statement Processing**: Data retrieval and aggregation

### 3. Performance Tests
- **Benchmarks**: Response time measurements
- **Load Testing**: High-traffic simulation

## Test Configuration

### pytest.ini Settings
- Coverage reporting enabled
- Warnings disabled for cleaner output
- Locust files excluded from default runs

### Fixtures (conftest.py)
- **client**: FastAPI TestClient instance
- **mock_s3**: Prevents real S3 interactions
- **mock_invoice_controller**: Stubs database operations
- **mock_supplier_controller**: Mocks supplier lookups
- **mock_invoice_upload_pipeline**: Avoids heavy file processing

## Running Specific Test Types

### Unit Tests Only
```bash
# Run tests that don't require database
pytest -k "not integration"
```

### Performance Benchmarks
```bash
# Run benchmark tests only
pytest -k "benchmark" --benchmark-only

# Run specific benchmark
pytest -k "test_health_benchmark" --benchmark-only
```

### Load Testing
```bash
# Run Locust load tests (separate from pytest)
locust -f mpi_backend/tests/test_load_smoke_locustfile.py --host=http://localhost:8000

# Or run with specific parameters
locust -f mpi_backend/tests/test_load_smoke_locustfile.py --host=http://localhost:8000 --users=100 --spawn-rate=10 --run-time=60s
```

## Test Coverage

### Current Coverage Areas
- ✅ Health endpoint
- ✅ Authentication bypass
- ✅ Filter validation
- ✅ Invoice operations (mocked)
- ✅ Statement endpoints
- ✅ File upload pipeline

### Coverage Report
```bash
# Generate HTML coverage report
pytest --cov=mpi_backend --cov-report=html

# View coverage in terminal
pytest --cov=mpi_backend --cov-report=term-missing
```

## Debugging Tests

### Verbose Output
```bash
# See detailed test output
pytest -v -s
```

### Debug Specific Test
```bash
# Run single test with debug output
pytest mpi_backend/tests/test_filters.py::test_filter_empty_request -v -s
```

### Check Test Discovery
```bash
# List all discovered tests
pytest --collect-only
```

## Test Data Management

### Database State
- Tests use mocked controllers to avoid database dependencies
- Real integration tests would require seeded test data
- Consider using test database with fixtures

### File Operations
- S3 operations are mocked
- File uploads create temporary files
- Excel exports are stubbed

## Continuous Integration

### GitHub Actions Example
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.9
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: pytest
      - name: Run benchmarks
        run: pytest -k "benchmark" --benchmark-only
```

## Troubleshooting

### Common Issues

**Import Errors (ModuleNotFoundError: No module named 'mpi_backend')**
```bash
# Solution 1: Use the helper script
python run_tests.py

# Solution 2: Set PYTHONPATH manually
export PYTHONPATH=$PYTHONPATH:$(pwd)
pytest

# Solution 3: Run from project root with explicit path
cd /path/to/mpi-backend
PYTHONPATH=. pytest
```

**Database Connection Issues**
```bash
# Tests use mocked controllers, but if you need real DB:
# 1. Ensure PostgreSQL is running
# 2. Run migrations: alembic upgrade head
# 3. Set up test database
```

**Performance Test Failures**
```bash
# Ensure server is running for load tests
uvicorn mpi_backend.main:app --host 0.0.0.0 --port 8000
```

## Adding New Tests

### Test File Structure
```python
# test_new_feature.py
def test_new_endpoint_success(client):
    """Test successful case"""
    response = client.get("/new-endpoint")
    assert response.status_code == 200

def test_new_endpoint_error(client):
    """Test error case"""
    response = client.post("/new-endpoint", json={})
    assert response.status_code == 422

@pytest.mark.benchmark(group="new-feature")
def test_new_endpoint_performance(client, benchmark):
    """Test performance"""
    def _call():
        return client.get("/new-endpoint")
    benchmark(_call)
```

### Test Naming Conventions
- `test_*_success`: Happy path tests
- `test_*_error`: Error handling tests
- `test_*_validation`: Input validation tests
- `test_*_benchmark`: Performance tests

## Performance Targets

### Response Time Goals
- Health endpoint: < 10ms
- Filter endpoints: < 100ms (with pagination)
- File operations: < 500ms (mocked)

### Load Test Targets
- 1000+ concurrent users
- 95th percentile < 200ms
- Error rate < 1%

## Contributing

When adding new tests:
1. Follow existing naming conventions
2. Add appropriate fixtures if needed
3. Include both success and error cases
4. Add performance tests for critical endpoints
5. Update this README if adding new test categories

## Test Maintenance

### Regular Tasks
- Update mocks when API changes
- Review and update performance baselines
- Ensure test data remains relevant
- Monitor test execution time

### Test Data Updates
- Update fixtures when models change
- Refresh test data periodically
- Validate mock responses match real API

---

For questions or issues with the test suite, check the main project documentation or create an issue in the repository. 