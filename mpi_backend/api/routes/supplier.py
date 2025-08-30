from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from mpi_backend.database import get_async_db
from mpi_backend.database.controllers.Suppliers import SupplierController
from mpi_backend.utils.auth.auth_bearer import JWTBearer

router = APIRouter(prefix="/supplier", tags=["Supplier"])
logger = logging.getLogger(__name__)


@router.get("")
async def get_supplier_list(
    db: AsyncSession = Depends(get_async_db),
    token: str = Depends(JWTBearer())
):
    """
    Get all suppliers in the system.
    
    **Summary:**
        Retrieves a complete list of all suppliers from the database.
        Returns a dictionary mapping supplier IDs to supplier names for
        easy lookup and integration with other parts of the system.
        
    **Authentication:**
        - **token** (`str`): JWT Bearer token required for access
        
    **Returns:**
        - **dict**: Dictionary with supplier ID as key and supplier name as value
        
    **Response Example:**
    ```json
    {
        "1": "ABC Plumbing Supplies",
        "2": "XYZ Hardware Store",
        "3": "World Wide Plumbing",
        "4": "Gotham Supply Co"
    }
    ```
    
    **Response Format:**
        - **Key**: Supplier ID (string)
        - **Value**: Supplier name (string)
        
    **Process Flow:**
        1. Authenticates user with JWT token
        2. Queries database for all suppliers
        3. Converts supplier objects to dictionary format
        4. Returns supplier ID to name mapping
        
    **Performance Features:**
        - Direct database query for all suppliers
        - Efficient dictionary conversion
        - Minimal data processing
        - Fast response time
        
    **Error Codes:**
        - **401**: Unauthorized (invalid or missing token)
        - **500**: Database error or server failure
        
    **Use Cases:**
        - Populating supplier dropdown menus
        - Supplier selection in forms
        - Data validation and lookup
        - Integration with other API endpoints
        
    **Notes:**
        - Returns all suppliers regardless of status
        - Supplier IDs are converted to strings for consistency
        - Empty dictionary returned if no suppliers exist
        - Logs successful retrieval with count
        - Comprehensive error logging for debugging
    """
    logger.info("GET /supplier - Fetching supplier list")
    try:
        suppliers = await SupplierController(db).get_all_suppliers()
        supplier_dict = {
            str(supplier.id): supplier.supplier_name 
            for supplier in suppliers
        }
        logger.info(
            f"GET /supplier - Successfully fetched "
            f"{len(supplier_dict)} suppliers"
        )
        return supplier_dict
    except Exception as e:
        logger.error(f"GET /supplier - Failed to fetch suppliers: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to fetch suppliers: {e}"
        )
