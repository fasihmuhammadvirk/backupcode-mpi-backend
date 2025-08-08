import os
import sys
import types
import pytest
from fastapi.testclient import TestClient

# Add the project root to Python path
project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, project_root)

from mpi_backend.main import app


@pytest.fixture(scope="session", autouse=True)
def _enable_pytest_auth_bypass():
    # Ensure JWTBearer bypass is active during tests
    os.environ["PYTEST_CURRENT_TEST"] = os.environ.get(
        "PYTEST_CURRENT_TEST", "1"
    )
    yield


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


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
        "mpi_backend.utils.invoice_convertor.convert_single_invoice",
        _dummy_convert_single_invoice,
    )
    monkeypatch.setattr(
        "mpi_backend.utils.extracted_data_processor.process_extracted_data",
        _dummy_process_extracted_data,
    )
    return True

