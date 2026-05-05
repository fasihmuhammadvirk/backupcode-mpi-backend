"""
Configuration for Google Sheets integration.

This module provides configuration options for interacting with Google Sheets,
particularly for the mapping sync functionality.
"""

import os
from typing import Dict, Any, List

def _load_skip_sheets() -> List[str]:
    """
    Reads the SKIP_SHEETS environment variable from the .env file.
    Expects a comma-separated string like 'Sheet1,Sheet2,Sheet3'.
    """
    raw_value = os.environ.get("SKIP_SHEETS", "")
    if not raw_value:
        # Initial defaults if variable is missing
        return ["ALL SYSTEMS", "ITEMS WITHOUT TEMPORARY GROUP NAME", "DUPLICATE ITEMS", "Organize"]
    
    # Split by comma and remove whitespace
    return [s.strip() for s in raw_value.replace('"', '').split(",") if s.strip()]

# Default Google Sheet ID used for item mappings
DEFAULT_SHEET_ID = os.environ.get(
    "GOOGLE_SHEET_ID", 
    "1eRGGwM4A2XTp0c5lJMp1_zCaShe9NNI_OcC9BO_-R0I"
)

# Google API key for accessing Google Sheets API
GOOGLE_API_KEY = os.environ.get(
    "GOOGLE_API_KEY", 
    "AIzaSyDB5T2qVuWgI5b0QuBPXV5P6t5dQ78Z_RE"
)

# Default output file path for storing extracted mapping data (export/backup).
DEFAULT_OUTPUT_FILE = os.environ.get(
    "MAPPING_OUTPUT_FILE",
    "mpi_backend/storage/fixtures/mapping_export.json",
)

# Sheets to skip during synchronization (Dynamically loaded from .env)
SKIP_SHEETS = _load_skip_sheets()

# Mapping configuration settings
MAPPING_CONFIG: Dict[str, Any] = {
    "batch_size": int(os.environ.get("MAPPING_BATCH_SIZE", "100")),
    "fuzzy_threshold": int(os.environ.get("MAPPING_FUZZY_THRESHOLD", "95")),
}