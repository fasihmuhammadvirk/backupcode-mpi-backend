from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from mpi_backend.database.controllers.ItemsMappingController import ItemsMappingController
from mpi_backend.database.schemas import ItemMappingsResponse, UpdateMappingRequest
from mpi_backend.utils.auth.auth_bearer import JWTBearer

router = APIRouter(prefix="/mapping", tags=['Item Mappings'])


@router.post("")
def update_item_mappings(request: UpdateMappingRequest, db: Session = Depends(get_db), token: str = Depends(JWTBearer())):
    """
    Update item mappings with validation to prevent temporary mappings from being saved permanently.
    """
    try:
        results = []
        permanent_count = 0
        temporary_redirected = 0
        
        for mapping in request.mapping:
            result = ItemsMappingController(db).update_mapping(request.supplier_id, mapping)
            results.append(result)
            
            if result.get("status") == "success":
                permanent_count += 1
            elif result.get("status") == "redirected_to_temporary":
                temporary_redirected += 1
        
        message = f"Processing completed: {permanent_count} permanent mappings"
        if temporary_redirected > 0:
            message += f", {temporary_redirected} redirected to temporary storage"
            
        return {
            "success": True, 
            "message": message,
            "details": {
                "permanent_mappings": permanent_count,
                "temporary_redirected": temporary_redirected,
                "results": results
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update item mapping : {e}")


@router.get("/search-item")
def search_item_mapping(
    item: str = Query(..., description="Clean item code from invoice to search for"),
    db: Session = Depends(get_db), 
    token: str = Depends(JWTBearer())
):
    """
    Search for item mappings by clean item code across all suppliers.
    
    This endpoint:
    - Takes a clean item code (from invoice)
    - Searches across ALL suppliers
    - Uses suffix cleaning to compare against database items
    - Returns all matching mappings found
    
    Args:
        item (str): The clean item code from invoice
        
    Returns:
        Dict containing:
        - found: boolean indicating if any mappings were found
        - total_matches: number of mappings found
        - matches: list of all matching mappings
        - item_searched: the clean item that was searched
    """
    try:
        result = ItemsMappingController(db).search_clean_item_across_suppliers(
            clean_item=item
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search item mapping: {e}")


@router.get("/mpi_types")
def get_mapping_by_mpi_type(db: Session = Depends(get_db), token: str = Depends(JWTBearer())):
    """
    Get all MPI type mappings.
    
    Returns:
        Dict: Dictionary with MPI codes as keys and mapping details as values
    """
    try:
        mappings = ItemsMappingController(db).get_items_mappings_by_mpi_type()
        return mappings
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch item mapping by MPI type: {e}")


@router.get("/{supplier_id}", response_model=List[ItemMappingsResponse])
def get_mapping_by_supplier_id(
    supplier_id: int, db: Session = Depends(get_db), token: str = Depends(JWTBearer())
):
    """
    Retrieve item mappings for a given supplier ID.

    This endpoint fetches item mappings associated with a specific supplier ID
    from the database. It uses pagination to handle large datasets by fetching
    data in batches of a specified size.

    Parameters:
        supplier_id (int): The ID of the supplier whose item mappings are to be retrieved.
        db (Session): The database session dependency.
        token (str): The JWT token for authentication.

    Returns:
        List[ItemMappingsResponse]: A list of item mappings for the specified supplier.

    Raises:
        HTTPException: If an error occurs during the retrieval process.
    """
    try:
        # adding pagination to handle the large data
        batch_size = 100  # Adjust based on expected dataset size
        mappings = []
        offset = 0

        while True:
            batch = ItemsMappingController(db).get_items_mappings_by_supplier_id(supplier_id, limit=batch_size, offset=offset)
            if not batch:
                break
            mappings.extend(batch)
            offset += batch_size  # Move to the next batch

        return mappings

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch item mapping: {e}")
