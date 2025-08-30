from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from mpi_backend.database import get_async_db
from mpi_backend.database.controllers.ItemsMappingController import ItemsMappingController
from mpi_backend.database.schemas import ItemMappingsResponse, UpdateMappingRequest
from mpi_backend.utils.auth.auth_bearer import JWTBearer

router = APIRouter(prefix="/mapping", tags=['Item Mappings'])


@router.post("")
async def update_item_mappings(
    request: UpdateMappingRequest, 
    db: AsyncSession = Depends(get_async_db), 
    token: str = Depends(JWTBearer())
):
    """
    Update item mappings with validation and temporary mapping handling.
    
    **Summary:**
        Updates multiple item mappings for a specific supplier with validation
        to prevent temporary mappings from being saved permanently. This endpoint
        processes batch updates and provides detailed feedback on the results.
        
    **Request Body:**
        - **request** (`UpdateMappingRequest`): Object containing:
            - **supplier_id** (`int`, required): The supplier ID for the mappings
            - **mapping** (`List[MappingItem]`, required): Array of mapping updates
            
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **Dict**: Update results containing:
            - **success** (`bool`): Overall success status
            - **message** (`str`): Summary message of the operation
            - **details** (`Dict`): Detailed breakdown of results:
                - **permanent_mappings** (`int`): Number of permanent mappings saved
                - **temporary_redirected** (`int`): Number redirected to temporary storage
                - **results** (`List[Dict]`): Individual mapping results
                
    **Response Example:**
    ```json
    {
        "success": true,
        "message": "Processing completed: 15 permanent mappings, 3 redirected to temporary storage",
        "details": {
            "permanent_mappings": 15,
            "temporary_redirected": 3,
            "results": [
                {
                    "status": "success",
                    "message": "Mapping updated successfully"
                },
                {
                    "status": "redirected_to_temporary",
                    "message": "Temporary mapping created"
                }
            ]
        }
    }
    ```
    
    **Processing Logic:**
        - Validates each mapping before processing
        - Prevents temporary mappings from being saved permanently
        - Redirects temporary mappings to appropriate storage
        - Provides individual status for each mapping update
        
    **Status Types:**
        - **success**: Mapping was successfully updated permanently
        - **redirected_to_temporary**: Mapping was redirected to temporary storage
        - **error**: Mapping update failed
        
    **Error Codes:**
        - **500**: Internal server error during mapping update
        
    **Notes:**
        - Processes mappings in batch for efficiency
        - Provides detailed feedback for each mapping processed
        - Maintains data integrity through validation
        - Temporary mappings are handled separately from permanent ones
    """
    try:
        results = []
        permanent_count = 0
        temporary_redirected = 0

        for mapping in request.mapping:
            # Normalize supplier_item_ids in request payload to avoid empty/whitespace-only inserts
            if isinstance(mapping.get("supplier_item_ids"), str) and mapping["supplier_item_ids"].strip() == "":
                results.append({
                    "status": "skipped_empty_item",
                    "message": "supplier_item_ids cannot be empty or whitespace",
                    "action": "no_change"
                })
                continue
            result = await ItemsMappingController(db).update_mapping(
                request.supplier_id, mapping)
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
        raise HTTPException(
            status_code=500, detail=f"Failed to update item mapping : {e}")


@router.get("/search-item")
async def search_item_mapping(
    item: str = Query(...,
                      description="Clean item code from invoice to search for"),
    db: AsyncSession = Depends(get_async_db),
    token: str = Depends(JWTBearer())
):
    """
    Search for item mappings by clean item code across all suppliers.
    
    **Summary:**
        Searches for item mappings across all suppliers using a clean item code
        from an invoice. This endpoint performs cross-supplier searches and uses
        suffix cleaning to find matches in the database.
        
    **Query Parameters:**
        - **item** (`str`, required): The clean item code from invoice to search for
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **Dict**: Search results containing:
            - **found** (`bool`): Whether any mappings were found
            - **total_matches** (`int`): Number of mappings found
            - **matches** (`List[Dict]`): List of all matching mappings
            - **item_searched** (`str`): The clean item that was searched
            
    **Response Example:**
    ```json
    {
        "found": true,
        "total_matches": 3,
        "item_searched": "ABC123",
        "matches": [
            {
                "supplier_id": 1,
                "supplier_name": "BMW Plumbing",
                "item_code": "ABC123-B",
                "mpi_item": "MPI001",
                "mpi_description": "Pipe Fitting"
            },
            {
                "supplier_id": 2,
                "supplier_name": "Flow Mark",
                "item_code": "ABC123-F",
                "mpi_item": "MPI001",
                "mpi_description": "Pipe Fitting"
            }
        ]
    }
    ```
    
    **Search Process:**
        - Takes a clean item code from invoice data
        - Searches across ALL suppliers in the system
        - Uses suffix cleaning to compare against database items
        - Returns all matching mappings found
        
    **Suffix Handling:**
        - Removes supplier-specific suffixes for comparison
        - Matches items across different suppliers
        - Returns full item codes with suffixes in results
        
    **Error Codes:**
        - **500**: Internal server error during search
        
    **Notes:**
        - Cross-supplier search capability
        - Handles item code variations with suffixes
        - Returns comprehensive matching information
        - Useful for finding duplicate items across suppliers
    """
    try:
        result = await ItemsMappingController(db).search_clean_item_across_suppliers(
            clean_item=item
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to search item mapping: {e}")


@router.get("/mpi_types")
async def get_mapping_by_mpi_type(db: AsyncSession = Depends(get_async_db), token: str = Depends(JWTBearer())):
    """
    Get all MPI type mappings organized by MPI code.
    
    **Summary:**
        Retrieves all item mappings organized by MPI (Master Product Index) codes.
        This provides a comprehensive view of how items are categorized and mapped
        across the system using the standardized MPI classification system.
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **Dict**: Dictionary with MPI codes as keys and mapping details as values
        
    **Response Example:**
    ```json
    {
        "MPI001": {
            "mpi_description": "Pipe Fittings",
            "mappings": [
                {
                    "supplier_id": 1,
                    "supplier_name": "BMW Plumbing",
                    "item_code": "ABC123-B",
                    "mpi_item": "MPI001",
                    "mpi_description": "Pipe Fittings"
                },
                {
                    "supplier_id": 2,
                    "supplier_name": "Flow Mark",
                    "item_code": "XYZ789-F",
                    "mpi_item": "MPI001",
                    "mpi_description": "Pipe Fittings"
                }
            ]
        },
        "MPI002": {
            "mpi_description": "Valves",
            "mappings": [
                {
                    "supplier_id": 1,
                    "supplier_name": "BMW Plumbing",
                    "item_code": "VAL456-B",
                    "mpi_item": "MPI002",
                    "mpi_description": "Valves"
                }
            ]
        }
    }
    ```
    
    **MPI Organization:**
        - Groups mappings by MPI code for easy categorization
        - Provides standardized product classification
        - Shows how items from different suppliers map to same MPI codes
        
    **Error Codes:**
        - **500**: Internal server error during data retrieval
        
    **Notes:**
        - Useful for understanding product categorization
        - Shows cross-supplier standardization
        - Helps identify duplicate items across suppliers
        - Supports inventory management and reporting
    """
    try:
        # Simple database connection check
        if not db:
            raise HTTPException(status_code=500, detail="Database connection error")
            
        mappings = await ItemsMappingController(db).get_items_mappings_by_mpi_type()
        
        # Return empty dict if no mappings found
        if mappings is None:
            return {}
            
        return mappings
        
    except Exception as e:
        # Log error and return simple error response
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error fetching MPI types: {str(e)}")
        
        raise HTTPException(
            status_code=500, 
            detail="Failed to fetch MPI types. Please try again."
        )


@router.get("/{supplier_id}", response_model=List[ItemMappingsResponse])
async def get_mapping_by_supplier_id(
    supplier_id: int, db: AsyncSession = Depends(get_async_db), token: str = Depends(JWTBearer())
):
    """
    Retrieve item mappings for a specific supplier ID with pagination.
    
    **Summary:**
        Fetches all item mappings associated with a specific supplier ID from
        the database. This endpoint uses internal pagination to handle large
        datasets efficiently by fetching data in batches.
        
    **Path Parameters:**
        - **supplier_id** (`int`, required): The ID of the supplier whose item mappings are to be retrieved
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **List[ItemMappingsResponse]**: Array of item mappings for the specified supplier
        
    **Response Example:**
    ```json
    [
        {
            "id": 1,
            "supplier_id": 1,
            "supplier_name": "BMW Plumbing",
            "item_code": "ABC123-B",
            "mpi_item": "MPI001",
            "mpi_description": "Pipe Fittings",
            "created_at": "2024-01-15T10:30:00Z",
            "updated_at": "2024-01-15T10:30:00Z"
        },
        {
            "id": 2,
            "supplier_id": 1,
            "supplier_name": "BMW Plumbing",
            "item_code": "XYZ789-B",
            "mpi_item": "MPI002",
            "mpi_description": "Valves",
            "created_at": "2024-01-15T11:00:00Z",
            "updated_at": "2024-01-15T11:00:00Z"
        }
    ]
    ```
    
    **Pagination Details:**
        - Internal batch processing with 100 items per batch
        - Automatically handles large datasets
        - No external pagination parameters required
        - Efficient memory usage for large supplier mappings
        
    **Performance Features:**
        - Batch processing to handle large datasets
        - Memory-efficient data retrieval
        - Automatic pagination without client intervention
        
    **Error Codes:**
        - **500**: Internal server error during data retrieval
        
    **Notes:**
        - Returns all mappings for the supplier (no limit on total results)
        - Uses internal pagination for performance optimization
        - Batch size is configurable (currently 100 items per batch)
        - Suitable for suppliers with large numbers of item mappings
        - Response includes full mapping details with timestamps
    """
    try:
        # adding pagination to handle the large data
        batch_size = 100  # Adjust based on expected dataset size
        mappings = []
        offset = 0

        while True:
            batch = await ItemsMappingController(db).get_items_mappings_by_supplier_id(
                supplier_id, limit=batch_size, offset=offset)
            if not batch:
                break
            mappings.extend(batch)
            offset += batch_size  # Move to the next batch

        return mappings

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch item mapping: {e}")
