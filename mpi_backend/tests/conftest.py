import os
import sys
import types
import pytest
from uuid import uuid4
from datetime import datetime

from fastapi.testclient import TestClient

# Add the project root to Python path
project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, project_root)

# Set up environment variables for testing
os.environ["JWT_SECRET"] = "test_secret_key_for_testing_only"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["GOOGLE_CHATBOT_API_KEY"] = "test-api-key"
os.environ["OPENAI_API_KEY"] = "test-openai-key"

from mpi_backend.database.schemas.InvoiceItems import InvoiceItems

@pytest.fixture
def sample_invoice_items()-> list[InvoiceItems]:
    return [
        InvoiceItems(
            id=1,
            filename="invoice_2024_01.xlsx",
            sheet_name="January",
            mpi_item="ABC-123",
            mpi_description="3/4 inch Pipe Fitting",
            item="ABC-123",
            description="3/4 inch Pipe Fitting",
            qty=10,
            cost=15.50,
            amount="155.00",
            date=datetime.strptime("01/15/2024", "%m/%d/%Y").date(),
            ref_no="REF-001",
            po_number="PO-12345",
            customer_job="Site A",
            bill="BILL-001",
            vendor="BMW Plumbing Supplies",
            class_="Class A",
            export_status="Pending",
            memo="Sample memo",
            buyer="John Doe",
            date_added=datetime.strptime("01/10/2024", "%m/%d/%Y").date(),
            invoice_id="550e8400-e29b-41d4-a716-446655440000",
            is_active=True,
            account="1000-Materials",
        ),
        InvoiceItems(
            id=2,
            filename="invoice_2024_01.xlsx",
            sheet_name="January",
            mpi_item="XYZ-789",
            mpi_description="1 inch Valve",
            item="XYZ-789",
            description="1 inch Valve",
            qty=5,
            cost=25.00,
            amount="125.00",
            date=datetime.strptime("01/20/2024", "%m/%d/%Y").date(),
            ref_no="REF-002",
            po_number="PO-002",
            customer_job="Site B",
            bill="BILL-002",
            vendor="Flow Mark",
            class_="Class B",
            export_status="Sent",
            memo="",
            buyer="Jane Smith",
            date_added=datetime.strptime("01/15/2024", "%m/%d/%Y").date(),
            invoice_id="550e8400-e29b-41d4-a716-446655440001",
            is_active=True,
            account="1001-Equipment",
        ),
    ]


# Realistic mock controller stub - defined at module level for reuse
class _RealisticInvoiceItemControllerStub:
    """Realistic mock that returns sample data matching actual business logic"""
    def __init__(self, db):
        self.db = db
        # Sample data representing typical invoice items
        self.sample_items = [
            {
                "id": 1,
                "filename": "invoice_2024_01.xlsx",
                "sheet_name": "January",
                "mpi_item": "ABC-123",
                "mpi_description": "3/4 inch Pipe Fitting",
                "item": "ABC-123",
                "description": "3/4 inch Pipe Fitting",
                "qty": 10,
                "cost": "15.50",
                "amount": "155.00",
                "date": "01/15/2024",
                "ref_no": "REF-001",
                "po_number": "PO-12345",
                "customer_job": "Site A",
                "bill": "BILL-001",
                "vendor": "BMW Plumbing Supplies",
                "class_": "Class A",
                "export_status": "Pending",
                "memo": "Sample memo",
                "buyer": "John Doe",
                "date_added": "01/10/2024",
                "invoice_id": "550e8400-e29b-41d4-a716-446655440000",
                "is_active": True,
                "account": "1000-Materials",
            },
            {
                "id": 2,
                "filename": "invoice_2024_01.xlsx",
                "sheet_name": "January",
                "mpi_item": "XYZ-789",
                "mpi_description": "1 inch Valve",
                "item": "XYZ-789",
                "description": "1 inch Valve",
                "qty": 5,
                "cost": "25.00",
                "amount": "125.00",
                "date": "01/20/2024",
                "ref_no": "REF-002",
                "po_number": "PO-002",
                "customer_job": "Site B",
                "bill": "BILL-002",
                "vendor": "Flow Mark",
                "class_": "Class B",
                "export_status": "Sent",
                "memo": "",
                "buyer": "Jane Smith",
                "date_added": "01/15/2024",
                "invoice_id": "550e8400-e29b-41d4-a716-446655440001",
                "is_active": True,
                "account": "1001-Equipment",
            },
            {
                "id": 3,
                "filename": "invoice_2024_02.xlsx",
                "sheet_name": "February",
                "mpi_item": "DEF-456",
                "mpi_description": "2 inch Connector",
                "item": "DEF-456",
                "description": "2 inch Connector",
                "qty": 15,
                "cost": "8.75",
                "amount": "131.25",
                "date": "02/05/2024",
                "ref_no": "REF-003",
                "po_number": "PO-003",
                "customer_job": "Site C",
                "bill": "BILL-003",
                "vendor": "World Wide Plumbing",
                "class_": "Class A",
                "export_status": "Pending",
                "memo": "Urgent order",
                "buyer": "Bob Wilson",
                "date_added": "02/01/2024",
                "invoice_id": "550e8400-e29b-41d4-a716-446655440002",
                "is_active": True,
                "account": "1000-Materials",
            },
        ]

    def get_invoice_items(self):
        return self.sample_items

    def apply_filters(self, request, page: int, size: int, col_param=None):
        """Realistic filter implementation that returns actual data"""
        filtered_items = self.sample_items.copy()

        # Apply filters if provided
        if hasattr(request, 'filters') and request.filters:
            for column_name, values in request.filters.items():
                if values:
                    filtered_items = [
                        item for item in filtered_items
                        if item.get(column_name) in values
                    ]

        # Add percentage_increase if color filter present
        if hasattr(request, 'color_filters') and request.color_filters:
            colors = getattr(request.color_filters, 'colors', [])
            for item in filtered_items:
                if 'green' in colors:
                    item['percentage_increase'] = 12.5
                elif 'orange' in colors:
                    item['percentage_increase'] = 6.0
                elif 'both' in colors:
                    item['percentage_increase'] = 8.0

        # Pagination
        total = len(filtered_items)
        start_idx = (page - 1) * size
        end_idx = start_idx + size
        paginated_items = filtered_items[start_idx:end_idx] if size > 0 else filtered_items
        total_pages = (total + size - 1) // size if size > 0 else 1

        return {
            "items": paginated_items,
            "total": total,
            "page": page,
            "size": size,
            "total_pages": total_pages,
            "has_next": end_idx < total,
            "has_prev": page > 1,
        }

    def get_data_by_column_name_paginated(self, column_name, page=1, limit=20, search="", filter_context=None, comparison_filters=None):
        if page <= 0:
            page = 1

        column_data = {
            "vendor": ["BMW Plumbing Supplies", "Flow Mark", "World Wide Plumbing"],
            "customer_job": ["Site A", "Site B", "Site C"],
            "item": ["ABC-123", "XYZ-789", "DEF-456"],
            "description": ["3/4 inch Pipe Fitting", "1 inch Valve", "2 inch Connector"],
        }

        data = column_data.get(column_name, [])
        if search:
            data = [d for d in data if search.lower() in d.lower()]

        total = len(data)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_data = data[start_idx:end_idx]
        total_pages = (total + limit - 1) // limit if total > 0 else 0

        return {
            "data": paginated_data,
            "page": page,
            "limit": limit,
            "total_records": total,
            "total_pages": total_pages,
        }
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test_db"

from mpi_backend.main import app
from mpi_backend.database.models.User import User



@pytest.fixture(scope="session", autouse=True)
def _setup_test_environment():
    # Disable scheduler during tests to prevent hanging
    os.environ["DISABLE_SCHEDULER"] = "1"
    yield


@pytest.fixture(scope="session")
def client():
    # Create a real FastAPI TestClient to test actual app startup and functionality
    try:
        return TestClient(app)
    except TypeError:
        # Fallback for older versions
        return TestClient(app=app)


# NOTE: db_session_mock fixture removed - unit tests now import MagicMock directly
# from unittest.mock import MagicMock for more explicit and flexible mocking.
# See tests/unit/controllers/ for examples of this pattern.


# ============================================================================
# INTEGRATION TEST FIXTURES (Real PostgreSQL Database via Testcontainers)
# ============================================================================

@pytest.fixture(scope="session")
def postgres_container():
    """
    Starts a PostgreSQL container for integration tests.

    This uses Testcontainers to spin up a real PostgreSQL database in Docker.
    The container runs for the entire test session and is automatically cleaned up.

    If Docker is not available, uses SQLite in-memory database as fallback.
    """
    try:
        from testcontainers.postgres import PostgresContainer
        
        # Start PostgreSQL container
        postgres = PostgresContainer("postgres:16")
        postgres.start()

        print(f"\n✅ Started PostgreSQL container: {postgres.get_connection_url()}")

        yield postgres

        # Cleanup: Stop container after all tests
        postgres.stop()
        print("\n✅ Stopped PostgreSQL container")
    except Exception as e:
        # Fallback to SQLite in-memory for tests when Docker not available
        print(f"\n⚠️  Docker not available, using SQLite fallback: {e}")
        from unittest.mock import MagicMock
        mock_container = MagicMock()
        mock_container.get_connection_url.return_value = "sqlite:///:memory:"
        yield mock_container


@pytest.fixture(scope="session")
def integration_db_engine(postgres_container):
    """
    Create a test database engine for integration tests using Testcontainers.

    This creates a SQLAlchemy engine connected to the PostgreSQL container.
    The engine is created once per test session and reused across tests.
    """
    from sqlalchemy import create_engine

    # Get connection URL from Testcontainer
    db_url = postgres_container.get_connection_url()

    # Create engine for test database
    engine = create_engine(db_url, pool_pre_ping=True)

    print(f"\n✅ Created database engine: {db_url}")

    yield engine

    # Cleanup
    engine.dispose()


@pytest.fixture(scope="session")
def setup_test_database_schema(integration_db_engine):
    """
    Create all database tables in the test database.

    This runs once per test session to set up the schema.
    """
    from mpi_backend.database import Base
    from sqlalchemy import text

    # Check if we're using PostgreSQL or SQLite
    db_url = str(integration_db_engine.url)
    is_postgres = 'postgresql' in db_url
    
    if is_postgres:
        # Enable PostgreSQL extensions needed for the schema
        with integration_db_engine.connect() as conn:
            # Enable citext extension for case-insensitive text columns
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
            # Enable pg_trgm extension for trigram indexes (used in search)
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            conn.commit()

        print("\n✅ Enabled PostgreSQL extensions (citext, pg_trgm)")
    else:
        print("\n⚠️  Using SQLite - PostgreSQL extensions skipped")

    # Create all tables
    Base.metadata.create_all(integration_db_engine)
    print("✅ Created all database tables in test database")

    yield

    # Cleanup: Drop all tables after tests (optional)
    # Base.metadata.drop_all(integration_db_engine)


@pytest.fixture
def db_session_integration(integration_db_engine, setup_test_database_schema):
    """
    Provides a real PostgreSQL database session for integration tests.

    Each test gets a fresh session with automatic rollback to ensure test isolation.
    This is a TRUE integration test fixture that:
    - Uses real PostgreSQL database
    - Creates real transactions
    - Tests actual SQL queries
    - Verifies data persistence

    Usage in tests:
        def test_create_user_integration(db_session_integration):
            from mpi_backend.database.controllers.UserController import UserController

            controller = UserController(db_session_integration)
            user = controller.create_user(username="test", password="test123")

            # Verify in real database
            assert user.id is not None
            db_session_integration.refresh(user)
            assert user.username == "test"
    """
    from sqlalchemy.orm import sessionmaker

    # Create session factory
    Session = sessionmaker(bind=integration_db_engine)
    session = Session()

    yield session

    # Rollback any changes to keep tests isolated
    session.rollback()
    session.close()


@pytest.fixture
def client_integration(db_session_integration, monkeypatch):
    """
    Provides a TestClient configured to use the real test database.

    This fixture:
    - Uses real PostgreSQL database for integration tests
    - Overrides get_db dependency to use test database
    - Allows full API endpoint testing with real database persistence

    Usage:
        def test_user_api_integration(client_integration, override_get_current_user):
            admin = User(id=uuid4(), username="admin", role="admin", is_active=True)

            with override_get_current_user(admin):
                response = client_integration.post("/users", json={...})
                assert response.status_code == 200
    """
    from mpi_backend.main import app
    from mpi_backend.database import get_db

    def override_get_db():
        """Override get_db to use test database session"""
        yield db_session_integration

    # Override the database dependency
    app.dependency_overrides[get_db] = override_get_db

    # Create test client
    test_client = TestClient(app)

    yield test_client

    # Cleanup
    app.dependency_overrides.clear()


@pytest.fixture
def seed_test_users(db_session_integration):
    """
    Seeds the test database with realistic user data for integration tests.

    Creates:
    - 1 admin user (no company)
    - 2 standard users (different companies)
    - 1 bookkeeping user
    - 1 inactive user

    Returns a dict with named access to seeded users.
    """
    from mpi_backend.database.models.User import User
    from mpi_backend.database.models.Company import Company
    from mpi_backend.database.controllers.UserController import UserController
    from uuid import uuid4

    # Create companies with unique names (to avoid conflicts between tests)
    # Using uuid4 ensures uniqueness across all test runs
    unique_id = str(uuid4())[:8]  # Short unique identifier
    company_a = Company(name=f"Test Company A {unique_id}")
    company_b = Company(name=f"Test Company B {unique_id}")
    db_session_integration.add_all([company_a, company_b])
    db_session_integration.flush()  # Flush to get the IDs without committing

    # Create users using controller (tests password hashing, etc.)
    controller = UserController(db_session_integration)

    admin_user = controller.create_user(
        username=f"admin_test_{unique_id}",
        password="admin123",
        email=f"admin_{unique_id}@test.com",
        role="admin",
        company_id=None
    )

    standard_user_1 = controller.create_user(
        username=f"user1_test_{unique_id}",
        password="user123",
        email=f"user1_{unique_id}@test.com",
        role="standard",
        company_id=company_a.id  # Use actual company ID from database
    )

    standard_user_2 = controller.create_user(
        username=f"user2_test_{unique_id}",
        password="user123",
        email=f"user2_{unique_id}@test.com",
        role="standard",
        company_id=company_b.id  # Use actual company ID from database
    )

    bookkeeping_user = controller.create_user(
        username=f"bookkeeper_test_{unique_id}",
        password="book123",
        email=f"bookkeeper_{unique_id}@test.com",
        role="bookkeeping",
        company_id=company_a.id  # Use actual company ID from database
    )

    # Create inactive user manually (controller creates active by default)
    inactive_user = User(
        id=uuid4(),
        username=f"inactive_test_{unique_id}",
        password=controller.hash_password("inactive123"),
        email=f"inactive_{unique_id}@test.com",
        role="standard",
        company_id=company_a.id,  # Use actual company ID from database
        is_active=False
    )
    db_session_integration.add(inactive_user)
    db_session_integration.flush()  # Flush but don't commit (will be rolled back)

    # Return dictionary for easy access in tests
    return {
        "admin": admin_user,
        "user1": standard_user_1,
        "user2": standard_user_2,
        "bookkeeper": bookkeeping_user,
        "inactive": inactive_user,
        "companies": {
            "company_a": company_a,
            "company_b": company_b
        }
    }


@pytest.fixture()
def mock_s3(monkeypatch):
    # Prevent real S3 interactions
    from mpi_backend.utils import s3_utils

    def _dummy_upload_file(file_name, file_key, is_invoice=True):
        return True

    def _dummy_get_presigned_url(
        file_key: str,
        expiration_time: int = 600,
        is_invoice: bool = True,
    ):
        return f"https://example.com/{file_key}?token=test"

    monkeypatch.setattr(s3_utils, "upload_file", _dummy_upload_file)
    monkeypatch.setattr(
        s3_utils,
        "get_presigned_url",
        _dummy_get_presigned_url,
    )
    return True


@pytest.fixture()
def mock_save_final_data(monkeypatch):
    # Avoid writing files during export endpoints
    from mpi_backend.utils.pdf_to_excel import formatting_util

    def _dummy_save_final_data(final_df, supplier: str, output_path: str):
        # Create empty file path if needed
        import os
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(b"")
        return output_path

    monkeypatch.setattr(
        formatting_util,
        "save_final_data",
        _dummy_save_final_data,
    )
    return True


@pytest.fixture()
def override_get_current_user():
    """
    Fixture that provides a context manager for overriding get_current_user dependency.

    This allows tests to simulate authenticated requests from users with different roles
    without needing to generate real JWT tokens or mock the entire authentication system.
    The fixture automatically cleans up the dependency override after the test completes.

    Usage:
        from mpi_backend.database.models.User import User
        from uuid import uuid4

        def test_standard_user_access(client, override_get_current_user):
            # Create a user with the desired role
            user = User(
                id=uuid4(),
                username='test_user',
                role='standard',
                company_id=1,
                is_active=True
            )

            # Use the context manager to override the dependency
            with override_get_current_user(user):
                # Make requests as this user
                res = client.get("/some-protected-endpoint")
                assert res.status_code == 200
                # Test role-based behavior...

        def test_admin_user_access(client, override_get_current_user):
            admin = User(
                id=uuid4(),
                username='admin',
                role='admin',
                company_id=None,
                is_active=True
            )

            with override_get_current_user(admin):
                res = client.get("/admin-endpoint")
                # Assertions...

    Note: The existing 'client' fixture will continue to work without authentication
    for endpoints that don't require it. This fixture is only needed for testing
    role-based access control on protected endpoints.
    """
    from mpi_backend.main import app
    from mpi_backend.utils.auth.dependencies import get_current_user
    from contextlib import contextmanager

    # Add a default if there wasn't a specific user provided 
    default_user = User(
        id=uuid4(),
        username='test_user',
        role='standard',
        company_id=1,
        is_active=True
    )

    @contextmanager
    def _override(user: User | None = default_user):
        """Context manager to override get_current_user dependency"""
        def mock_get_current_user():
            return user

        app.dependency_overrides[get_current_user] = mock_get_current_user
        try:
            yield
        finally:
            app.dependency_overrides.clear()

    return _override


@pytest.fixture()
def mock_invoice_controller(monkeypatch):
    # Stub methods to avoid DB usage where appropriate
    from mpi_backend.database.controllers import Invoice
    from mpi_backend.database.controllers import InvoiceItems
    import mpi_backend.api.routes.filters as filters_module
    import mpi_backend.api.routes.invoices_list as invoices_module

    class _InvoiceControllerStub:
        def __init__(self, db):
            pass

        def get_invoices(self, **kwargs):
            return {
                "items": [],
                "total": 0,
                "page": kwargs.get("page", 1),
                "size": kwargs.get("page_size", 10),
                "pages": 0,
            }

        def get_invoice_by_invoiceID(self, invoice_id, db):
            # Minimal object-like response
            return types.SimpleNamespace(
                id=invoice_id,
                filename="test.pdf",
                supplier_id=1,
            )

        def get_all_invoices(self, **kwargs):
            return []

        def sort(self, db, column, sort_order):
            return []

        def delete_invoice(self, invoice_id, db):
            return invoice_id

    class _InvoiceItemControllerStub:
        def __init__(self, db):
            pass

        def get_invoice_items(self):
            return []

        def apply_filters(self, request, page: int, size: int, col_param=None):
            return {
                "items": [],
                "total": 0,
                "page": page,
                "size": size,
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
            }

        def get_aggregates(self, request):
            return {
                "total_amount": 0.0,
                "total_quantity": 0,
                "average_cost": 0.0,
                "item_count": 0,
                "invoice_count": 0,
                "supplier_count": 0,
            }

        def get_price_history(self, request):
            return []

        def get_data_by_column_name_paginated(self, column_name, page=1, limit=20, search="", filter_context=None, comparison_filters=None):
            # Handle invalid page numbers gracefully
            if page <= 0:
                page = 1
            return {
                "data": [],
                "page": page,
                "limit": limit,
                "total_records": 0,
                "total_pages": 0,
            }

    # Patch controllers where used
    monkeypatch.setattr(Invoice, "InvoiceController", _InvoiceControllerStub)
    monkeypatch.setattr(
        InvoiceItems,
        "InvoiceItemController",
        _InvoiceItemControllerStub,
    )
    # Critical: patch the symbols imported in routers
    monkeypatch.setattr(
        filters_module,
        "InvoiceItemController",
        _InvoiceItemControllerStub,
    )
    monkeypatch.setattr(
        invoices_module,
        "InvoiceController",
        _InvoiceControllerStub,
    )
    return True


@pytest.fixture()
def realistic_mock_invoice_controller(monkeypatch):
    """Realistic mock that returns sample data for testing actual business logic
    TODO: Review this, this might not be the best way or place to mock this controller
    """
    from mpi_backend.database.controllers import InvoiceItems
    from mpi_backend.api.routes import filters as filters_module

    monkeypatch.setattr(
        InvoiceItems,
        "InvoiceItemController",
        _RealisticInvoiceItemControllerStub,
    )
    monkeypatch.setattr(
        filters_module,
        "InvoiceItemController",
        _RealisticInvoiceItemControllerStub,
    )
    return True


@pytest.fixture()
def mock_supplier_controller(monkeypatch):
    from mpi_backend.database.controllers import Suppliers

    class _SupplierControllerStub:
        def __init__(self, db):
            pass

        def get_supplier_by_id(self, supplier_id: int):
            return "Supplier-Stub"

    monkeypatch.setattr(
        Suppliers,
        "SupplierController",
        _SupplierControllerStub,
    )
    return True


@pytest.fixture()
def mock_invoice_upload_pipeline(monkeypatch, tmp_path, mock_s3):
    # Mock invoice conversion and processing to avoid heavy operations
    # Avoid unused var warnings by not binding originals

    def _dummy_convert_single_invoice(file_path, supplier):
        return [file_path], []

    def _dummy_process_extracted_data(
        converted_files, failed_files, existing_invoice_id=None
    ):
        return [{
            "status": "created",
            "message": "Invoice processed successfully",
            "filename": "invoice_001.pdf",
            "supplier": "Supplier-Stub",
            "invoice_id": "11111111-1111-1111-1111-111111111111",
            "ref_no": "REF-001",
            "vendor": "Vendor-Stub",
            "date": "2024-01-01",
        }]

    monkeypatch.setattr(
        "mpi_backend.utils.invoice_converter.convert_single_invoice",
        _dummy_convert_single_invoice,
    )
    monkeypatch.setattr(
        "mpi_backend.utils.extracted_data_processor.process_extracted_data",
        _dummy_process_extracted_data,
    )
    return True
