"""
PDF text extraction utilities for invoice processing.

This module provides functions to extract text from PDF files for validation
and hallucination checking purposes.
"""
import fitz  # PyMuPDF
import logging
from pathlib import Path
import re

logger = logging.getLogger(__name__)

def _normalize_numeric_string(value: str) -> str:
    """
    Normalize a numeric string by removing formatting and converting to standard form.
    
    This helper function cleans numeric strings by removing currency symbols,
    commas, and other non-numeric characters, then converts them to a normalized
    string representation (integer if whole number, float otherwise).
    
    Args:
        value: String that may contain a numeric value with formatting
            (e.g., "$1,234.50", "1234.5", "-42").
    
    Returns:
        str: Normalized numeric string. If the value is a whole number, returns
            integer format (e.g., "1234"). If it has decimal places, returns
            float format with trailing zeros removed (e.g., "1234.5").
            If the value cannot be parsed as a number, returns the original
            string unchanged.
    
    Examples:
        >>> _normalize_numeric_string("$1,234.50")
        '1234.5'
        >>> _normalize_numeric_string("42")
        '42'
        >>> _normalize_numeric_string("-123.00")
        '-123'
        >>> _normalize_numeric_string("not a number")
        'not a number'
    """
    try:
        cleaned = re.sub(r'[^\d\.\-]', '', value)
        if cleaned and ('.' in cleaned or cleaned.replace('-', '').isdigit()):
            num = float(cleaned)
            if num == int(num):
                return str(int(num))
            else:
                return str(num).rstrip('0').rstrip('.')
    except (ValueError, TypeError):
        pass
    
    # If not a valid number, return original
    return value

def normalize_text_to_tokens(text: str) -> list[str]:
    """
    Normalize text by removing currency symbols and commas, normalizing whitespace,
    and normalizing numeric values. Returns a list of normalized tokens.
    
    This function can be used to normalize both PDF text and extracted data values
    to ensure consistent comparison.
    
    Args:
        text: String to normalize (can be PDF text or extracted field value)
    
    Returns:
        list[str]: List of normalized text tokens. Numeric values are normalized
            (e.g., "1,234.50" -> "1234.5"), currency symbols and commas are removed,
            and all whitespace is normalized to single spaces before splitting.
    
    Examples:
        >>> normalize_text_to_tokens("Total: $1,234.50")
        ['Total:', '1234.5']
        >>> normalize_text_to_tokens("Item 42 - Description")
        ['Item', '42', '-', 'Description']
    """
    normalized = re.sub(r"\s+", " ", text.replace("$", "").replace(",", ""))
    tokens = normalized.split()
    
    int_pattern = r"^-?\d+$"
    float_pattern = r"^-?\d*\.\d+$"
    # Match numbers with trailing letters (e.g., "371.36T" for Taxable amounts)
    numeric_with_suffix_pattern = r"^-?\d+\.?\d*[A-Za-z]$"

    for i in range(len(tokens)):
        if re.match(int_pattern, tokens[i]) or re.match(float_pattern, tokens[i]) or re.match(numeric_with_suffix_pattern, tokens[i]):
            tokens[i] = _normalize_numeric_string(tokens[i])
    
    return tokens

def extract_text_from_pdf(filename: str) -> str:
    """
    Extract full text from a PDF file.
    
    This function opens a PDF file using a context manager and extracts all text
    content from all pages, returning the concatenated text. This is used for
    validating extracted invoice data against the actual PDF content to detect
    hallucinations.
    
    Args:
        filename: Path to the PDF file to extract text from. Can be a string
            path or Path object. The file must exist and be a valid PDF.
    
    Returns:
        str: All text extracted from the PDF, concatenated from all pages.
            Empty string if extraction fails, PDF is empty, or if an error
            occurs during processing (except FileNotFoundError which is raised).
    
    Raises:
        FileNotFoundError: If the PDF file does not exist at the specified path.
            This exception is raised by PyMuPDF when attempting to open the file.
        ValueError: If the path is invalid or the file cannot be opened as a PDF.
    
    Example:
        >>> text = extract_text_from_pdf("/path/to/invoice.pdf")
        >>> print(f"Extracted {len(text)} characters")
        Extracted 1234 characters
    
    Note:
        Uses PyMuPDF (fitz) library for PDF text extraction with a context manager
        to ensure proper resource cleanup. The text is extracted in page order and
        concatenated with newlines between pages. Whitespace and formatting are
        preserved as much as possible from the original PDF. If text extraction fails
        for a specific page, a warning is logged but processing continues with
        other pages.
    """
    try:
        # Open PDF document using context manager
        with fitz.open(filename) as doc:
            page_count = len(doc)
            
            if page_count == 0:
                logger.warning(f"PDF file has no pages: {filename}")
                return ""
            
            # Extract text from all pages
            full_text = ""
            for page_num in range(page_count):
                try:
                    page = doc[page_num]
                    page_text = page.get_text()
                    if page_text:
                        full_text += page_text
                        # Add page separator for multi-page documents
                        if page_num < page_count - 1:
                            full_text += "\n"
                except Exception as e:
                    logger.warning(
                        f"Error extracting text from page {page_num + 1} of {filename}: {e}"
                    )
         
        if full_text:
            logger.info(
                f"Successfully extracted {len(full_text)} characters from "
                f"{page_count} page(s) in {filename}"
            )
        else:
            logger.warning(
                 f"No text extracted from PDF (may be image-based or scanned): {filename}"
            )
        return full_text
         
    except (FileNotFoundError, ValueError): 
        raise
    except Exception as e:
        error_msg = f"Error extracting text from PDF {filename}: {str(e)}"
  
        logger.exception(error_msg) 
        return ""

def normalize_pdf_text(filename: str) -> tuple[set[str], str]:
    """
    Extract and normalize text from a PDF file into a set of tokens.
    
    This function extracts all text from a PDF, normalizes it by removing
    currency symbols and commas, normalizes numeric values, and returns a
    set of word tokens. This normalized set is used for validating extracted
    invoice data against the source PDF to detect hallucinations.
    
    Args:
        filename: Path to the PDF file to extract and normalize text from.
            The file must exist and be a valid PDF.
    
    Returns:
        set[str]: Set of normalized text tokens from the PDF. Numeric values
            are normalized (e.g., "1,234.50" -> "1234.5"), currency symbols
            and commas are removed, and all whitespace is normalized to single
            spaces before splitting into tokens.
        str: The entire raw PDF text
    
    Note:
        This function is used in the validation pipeline to verify that extracted
        field values actually exist in the source PDF. The normalization ensures
        that numeric values match regardless of formatting differences.
    
    Raises:
        FileNotFoundError: If the PDF file does not exist at the specified path.
        Exception: Other exceptions from extract_text_from_pdf() are caught and
            logged, returning an empty set.
    """
    raw_pdf_text = extract_text_from_pdf(filename)
    tokens = normalize_text_to_tokens(raw_pdf_text)
    return set(tokens), raw_pdf_text
