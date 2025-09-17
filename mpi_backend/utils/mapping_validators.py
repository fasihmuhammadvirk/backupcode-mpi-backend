"""
Mapping validation utilities to prevent temporary placeholders from being saved as permanent mappings.
"""
import re
from typing import Dict, Tuple, Optional, List


# Define what constitutes temporary/placeholder mappings
TEMPORARY_MPI_PATTERNS = [
    r'^UIDI',           # Any UIDI codes
    r'^No Match',       # No Match variations
    r'^Temp',           # Temporary codes
    r'^TEMP',           # Uppercase temporary
    r'^TMP',            # Abbreviated temporary
    r'^PLACEHOLDER',    # Explicit placeholders
]

TEMPORARY_DESCRIPTIONS = [
    'No Match',
    'No Match / UIDI',
    'UIDI',
    'Temporary',
    'Placeholder',
    'Unknown',
    'TBD',
    'To Be Determined',
]


def is_temporary_mapping(mpi_code: Optional[str], description: Optional[str] = None, supplier: Optional[str] = None) -> bool:
    """
    Check if an MPI code or description represents a temporary/placeholder mapping.

    Args:
        mpi_code: The MPI code to validate
        description: Optional description to check
        supplier: Optional supplier name to check

    Returns:
        bool: True if this is a temporary mapping that should NOT be saved permanently
    """
    # Check if supplier is explicitly marked as Temporary
    if supplier and supplier.lower() == "temporary":
        return True

    if not mpi_code:
        return True  # Empty/null codes are temporary

    # Check MPI code patterns
    for pattern in TEMPORARY_MPI_PATTERNS:
        if re.match(pattern, mpi_code, re.IGNORECASE):
            return True

    # Check description if provided
    if description:
        for temp_desc in TEMPORARY_DESCRIPTIONS:
            if temp_desc.lower() in description.lower():
                return True

    return False


def validate_mapping_for_permanent_storage(mapping_data: Dict) -> Tuple[bool, List[str]]:
    """
    Validate that a mapping is suitable for permanent storage in supplier_item_mappings.

    Args:
        mapping_data: Dictionary containing mapping fields

    Returns:
        Tuple[bool, List[str]]: (is_valid, list_of_errors)
    """
    errors = []

    mpi_code = mapping_data.get('mpi_code', '').strip()
    description = mapping_data.get('description', '').strip()
    supplier_item_ids = mapping_data.get('supplier_item_ids', '').strip()

    # Check if this is a temporary mapping
    if is_temporary_mapping(mpi_code, description, mapping_data.get('supplier')):
        errors.append(
            f"Temporary mapping detected: '{mpi_code}' should not be stored as permanent mapping"
        )

    # Modified validation: Allow empty MPI code if there's a valid description and supplier_item_ids
    # This handles cases like FLUX9-F where MPI code is empty but item_code and description exist
    if not mpi_code:
        # Only require MPI code if there's no description or supplier_item_ids
        if not description or not supplier_item_ids:
            errors.append(
                "MPI code is required when description or supplier item IDs are missing")
    else:
        # If MPI code exists, validate its format
        if len(mpi_code.strip()) < 2:
            errors.append(
                f"MPI code too short: '{mpi_code}' - may be placeholder"
            )

    if not supplier_item_ids:
        errors.append("Supplier item IDs are required and cannot be empty")

    # Check for suspicious patterns in supplier_item_ids
    if supplier_item_ids and any(
        temp in supplier_item_ids.upper() for temp in ['UIDI', 'NO MATCH', 'TEMP']
    ):
        errors.append(
            f"Supplier item IDs contain temporary placeholders: '{supplier_item_ids}'"
        )

    return len(errors) == 0, errors


def should_use_temporary_storage(mpi_code: Optional[str], description: Optional[str] = None) -> bool:
    """
    Determine if a mapping should be stored in temporary_item_mappings instead of supplier_item_mappings.

    Args:
        mpi_code: The MPI code
        description: Optional description

    Returns:
        bool: True if should use temporary storage
    """
    return is_temporary_mapping(mpi_code, description)


def clean_mapping_data(mapping_data: Dict) -> Dict:
    """
    Clean and normalize mapping data before validation.

    Args:
        mapping_data: Raw mapping data

    Returns:
        Dict: Cleaned mapping data
    """
    cleaned = {}

    for key, value in mapping_data.items():
        if isinstance(value, str):
            # Strip whitespace and normalize
            cleaned[key] = value.strip()
        else:
            cleaned[key] = value

    return cleaned


def get_mapping_storage_recommendation(mapping_data: Dict) -> Dict:
    """
    Get recommendation for where a mapping should be stored.

    Args:
        mapping_data: Mapping data to analyze

    Returns:
        Dict with storage recommendation and reasoning
    """
    cleaned_data = clean_mapping_data(mapping_data)
    is_valid, errors = validate_mapping_for_permanent_storage(cleaned_data)

    if is_valid:
        return {
            "storage": "permanent",
            "table": "supplier_item_mappings",
            "reason": "Valid permanent mapping",
            "errors": []
        }
    else:
        return {
            "storage": "temporary",
            "table": "temporary_item_mappings",
            "reason": "Contains temporary/placeholder data",
            "errors": errors
        }


def validate_bulk_mappings(mappings_list: List[Dict]) -> Dict:
    """
    Validate a list of mappings and categorize them.

    Args:
        mappings_list: List of mapping dictionaries

    Returns:
        Dict with validation results and categorization
    """
    valid_permanent = []
    temporary_only = []
    invalid = []

    for i, mapping in enumerate(mappings_list):
        try:
            recommendation = get_mapping_storage_recommendation(mapping)

            if recommendation["storage"] == "permanent":
                valid_permanent.append({"index": i, "mapping": mapping})
            elif recommendation["storage"] == "temporary":
                temporary_only.append({
                    "index": i,
                    "mapping": mapping,
                    "errors": recommendation["errors"]
                })
            else:
                invalid.append({
                    "index": i,
                    "mapping": mapping,
                    "errors": recommendation["errors"]
                })
        except Exception as e:
            invalid.append({
                "index": i,
                "mapping": mapping,
                "errors": [f"Validation error: {str(e)}"]
            })

    return {
        "total_mappings": len(mappings_list),
        "valid_permanent": len(valid_permanent),
        "temporary_only": len(temporary_only),
        "invalid": len(invalid),
        "permanent_mappings": valid_permanent,
        "temporary_mappings": temporary_only,
        "invalid_mappings": invalid
    }
