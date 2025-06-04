"""
Statement Extractor Module

This module provides tools to extract data from supplier statement PDFs.
It is designed to handle statements from various suppliers with a common interface.
"""

from mpi_backend.utils.statement_extractor.extractor import StatementExtractor, process_statement
from mpi_backend.utils.statement_extractor.statement_utils import (
    extract_text_from_pdf,
    identify_supplier,
    extract_statement_metadata,
    extract_summary_data
)

__all__ = [
    'StatementExtractor',
    'process_statement',
    'extract_text_from_pdf',
    'identify_supplier',
    'extract_statement_metadata',
    'extract_summary_data'
] 