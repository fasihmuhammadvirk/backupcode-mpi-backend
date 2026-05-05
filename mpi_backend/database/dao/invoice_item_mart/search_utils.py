"""
Search utility functions for determining search mode and building search conditions.

This module provides utilities for three search modes:
1. Onword search (default): Match only when a word begins with the search text
2. Substring search: Match anywhere inside the string (enabled via UI toggle)
3. Full text exact match: Exact case-sensitive match (using quotes)
"""

from dataclasses import dataclass
from enum import Enum


class SearchMode(str, Enum):
    """
    Search mode enumeration for autocomplete search behavior.

    Modes:
    - EXACT: Full text exact match (case-sensitive), triggered by quoted search
    - SUBSTRING: Match anywhere inside the string (case-insensitive)
    - ONWORD: Match only when a word begins with the search text (default)
    """
    EXACT = "exact"
    SUBSTRING = "substring"
    ONWORD = "onword"


@dataclass
class SearchModeResult:
    """
    Result of search mode determination.

    Attributes:
        mode: The determined search mode
        search_term: Cleaned search term with quotes stripped and whitespace trimmed
    """
    mode: SearchMode
    search_term: str


def determine_search_mode(
    search: str,
    substring_search: bool = False
) -> SearchModeResult:
    """
    Determine search mode based on search term and toggle state.

    Search mode precedence:
    1. Quoted search ("...") → Full text exact match (case-sensitive)
    2. Substring Search toggle ON → Substring search (case-insensitive)
    3. Default → Onword search (case-insensitive)

    Args:
        search: Search term (may be quoted for exact match)
        substring_search: Whether substring search toggle is enabled

    Returns:
        SearchModeResult containing the mode and cleaned search term
    """
    # Trim outer whitespace first
    search = search.strip() if search else ""

    # Check for quoted search (exact match) - highest priority
    if search.startswith('"') and search.endswith('"') and len(search) > 2:
        # Strip quotes and trim inner whitespace
        # Example: " *abc " → "*abc" → "*abc" (trimmed)
        # Example: " abc " → "abc" → "abc" (trimmed)
        cleaned_term = search[1:-1].strip()
        return SearchModeResult(mode=SearchMode.EXACT, search_term=cleaned_term)

    # For non-quoted searches, trim whitespace
    search = search.strip()

    # Check substring search toggle
    if substring_search:
        return SearchModeResult(mode=SearchMode.SUBSTRING, search_term=search)

    # Default: onword search
    return SearchModeResult(mode=SearchMode.ONWORD, search_term=search)


def normalize_search_term(search: str) -> str:
    """
    Normalize search term for fuzzy pattern matching.

    Mirrors the REGEXP_REPLACE(LOWER(...), '[-_\\s\\(\\)]+', ' ', 'g') logic used
    to compute *_normalized columns in the mart so that search patterns align with
    stored values. Specifically: dashes, underscores, and parentheses are replaced
    with a space (not stripped) so that e.g. "Amount-BR" normalizes to "amount br"
    matching item_normalized = "... amount br", not "amountbr".

    Args:
        search: Raw search term

    Returns:
        Normalized search term
    """
    if not search:
        return ""
    import re
    return re.sub(r'\s+', ' ', re.sub(r'[-_()\s]+', ' ', search.lower())).strip()


def escape_like_pattern(search: str) -> str:
    """
    Escape special characters in search term for use in SQL LIKE/ILIKE patterns.
    
    Escapes '%' and '_' characters which are special in LIKE patterns.
    
    Args:
        search: Raw search term
        
    Returns:
        Escaped search term safe for use in LIKE/ILIKE patterns
    """
    if not search:
        return ""
    # Escape backslashes first, then escape % and _
    return search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
