import logging
from sqlalchemy.orm import Session
from mpi_backend.database.dao.supplier_comparison_dao import SupplierComparisonDAO
from mpi_backend.database.schemas.SupplierComparison import (
    SupplierComparisonRequest,
    SupplierComparisonResponse,
    SupplierComparisonSummary,
    SupplierComparisonTableItem
)

logger = logging.getLogger(__name__)

class SupplierComparison:
    def __init__(self, db: Session):
        self.db = db
        self.dao = SupplierComparisonDAO()

    def get_comparison_summary(self, request: SupplierComparisonRequest) -> SupplierComparisonSummary | None:
        """
        Get summary statistics for the dashboard.
        """
        logger.info(f"Fetching comparison summary with request: {request}")
        data = self.dao.get_comparison_summary(self.db, request)
        if not data:
            return None
        return SupplierComparisonSummary.from_dict(data)

    def get_comparison_table(self, request: SupplierComparisonRequest) -> SupplierComparisonResponse:
        """
        Get the supplier comparison table data with pagination and nested details.
        """
        logger.info(f"Fetching comparison table with request: {request}")
        rows, total_count = self.dao.get_comparison_table(self.db, request, request.page_size, (request.page - 1) * request.page_size)
        
        items = [SupplierComparisonTableItem.from_dict(row) for row in rows]

        return SupplierComparisonResponse(
            items=items,
            total_count=total_count,
            page=request.page,
            page_size=request.page_size
        )

    def export_comparison_data(self, request: SupplierComparisonRequest, background_tasks=None):
        """
        Export all comparison data to CSV.
        """
        logger.info(f"Exporting comparison data with request: {request}")
        from mpi_backend.utils import export_utils

        rows, _ = self.dao.get_comparison_table(self.db, request, limit=None, offset=None)
        if not rows:
            raise ValueError("No data available to export")

        # Flatten the data for export with formatting
        export_rows = []
        for row in rows:
            item_data = dict(row)
            vendor_list = item_data.pop('vendor_details', [])
            
            is_first_row = True
            for vendor in vendor_list:
                # Build the row dictionary ensuring Item Code and Description are first
                row_dict = {
                    "mpi_item": item_data['item_mpi_code'] if is_first_row else "",
                    "description": item_data['item_description'] if is_first_row else "",
                    "quotes_count": item_data['quotes_count'],
                    "best_price": item_data['best_price'],
                    "potential_savings": item_data['potential_savings'],
                    **vendor
                }
                export_rows.append(row_dict)
                is_first_row = False

        return export_utils.export_generic(
            items=export_rows,
            columns=[
                "MPI Item Code", "Description", "Quotes Count", "Ref NO", "Market Best Price",
                "Potential Savings", "Supplier Name", "Purchase Date",
                "Quantity", "Unit Price", "Variance Amount", "Variance Percentage", 
                "Is Best Value", "Is Worst Purchase"
            ],
            background_tasks=background_tasks,
            filename_prefix="supplier_comparison_export"
        )
