"""
Shared constants for invoice_items_map DAO and related schemas/controllers.
"""

# Centralized mapping for group_by values coming from API to actual SQL columns.
# Keep this list tightly controlled to avoid SQL injection risks; only these keys are interpolated.
GROUP_BY_MAP = {
    "supplier": "supplier",
    "status": "mapping_type",
    "date": "date",
    "sheet": "sheet_name",
}

# Allowed values for group_by at the API boundary.
ALLOWED_GROUP_BY = set(["none", *GROUP_BY_MAP.keys()])

