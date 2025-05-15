"""
Configuration for Google Sheets integration.

This module provides configuration options for interacting with Google Sheets,
particularly for the mapping sync functionality.
"""

import os
from typing import Dict, Any

# Default Google Sheet ID used for item mappings
DEFAULT_SHEET_ID = os.environ.get(
    "GOOGLE_SHEET_ID", 
    "1eRGGwM4A2XTp0c5lJMp1_zCaShe9NNI_OcC9BO_-R0I"
)

# Google API key for accessing Google Sheets API
GOOGLE_API_KEY = os.environ.get(
    "GOOGLE_API_KEY", 
    "AIzaSyAeMGjLedlaT12NpFTUhrEzkUBtvT-9EsY"
)

# Default output file path for storing extracted mapping data
DEFAULT_OUTPUT_FILE = os.environ.get(
    "MAPPING_OUTPUT_FILE", 
    "mpi_backend/storage/fixtures/item-mapping.json"
)

# Sheets to skip during synchronization
SKIP_SHEETS = [
    "(AB, ALL SYSTEMS)", 
    "(AC, ITEMS WITHOUT TEMPORARY GROUP NAME)"
]

# Mapping configuration settings
MAPPING_CONFIG: Dict[str, Any] = {
    "batch_size": int(os.environ.get("MAPPING_BATCH_SIZE", "100")),
    "fuzzy_threshold": int(os.environ.get("MAPPING_FUZZY_THRESHOLD", "75")),
} 