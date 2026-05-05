"""
Document Type Classifier for PDF Files

This module provides simple keyword-based classification to identify document types
and filter out non-invoice/credit documents from the processing pipeline.

Extends the existing pattern-based classification system used for supplier
identification and credit memo detection.
"""

import logging
import re
from dataclasses import dataclass
from typing import ClassVar, Literal, Optional

import fitz

from mpi_backend.utils.document_types import DocumentType

HEADER_LINES_COUNT = 60
FIRST_LINES_COUNT = 3

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClassificationResult:
    doc_type: DocumentType
    confidence: float
    details: dict

    @property
    def is_invoice_or_credit(self) -> bool:
        return self.doc_type.is_invoice_like

    @property
    def requires_manual_review(self) -> bool:
        """Returns True if confidence is in medium range requiring manual review."""
        return 0.7 <= self.confidence < 0.95


@dataclass(frozen=True)
class _Rule:
    """A single declarative classification rule."""

    doc_type: DocumentType
    pattern: str
    reason: str
    match: Literal["startswith", "contains", "regex"] = "startswith"
    scope: Literal["first_lines", "first_lines_rest", "header_lines", "full_header"] = "first_lines"
    confidence: float = 1.0
    exclude: tuple[str, ...] = ()
    exclude_scope: Literal["line", "header"] = "line"


class DocumentClassifier:
    """Header-based PDF document classifier.

    All methods are classmethods -- no instance state is needed.
    """

    RULES: ClassVar[list[_Rule]] = [
        # ==================== TIER 1: HIGH-CONFIDENCE INVOICE/CREDIT PATTERNS ====================
        # These run first to catch clear invoice/credit documents before noise filters can interfere

        # -- Primary Invoice Detection (High Confidence) --
        _Rule(DocumentType.INVOICE,   "INVOICE",     "INVOICE header"),
        _Rule(DocumentType.INVOICE,   r'I\s+N\s+V\s+O\s+I\s+C\s+E', "Spaced INVOICE header", match="regex"),

        # -- Primary Credit Detection (High Confidence) --
        _Rule(DocumentType.CREDIT,    "CREDIT MEMO", "CREDIT MEMO header"),
        _Rule(DocumentType.CREDIT,    "CREDIT",      "CREDIT header", confidence=0.9, exclude=("CREDIT TERMS", "CREDIT LIMIT", "CREDIT CARD")),

        # -- Primary Statement Detection (High Confidence) --
        _Rule(DocumentType.STATEMENT, "STATEMENT",   "STATEMENT header"),

        # ==================== TIER 2: CLEAR OTHER INDICATORS ====================
        # High-confidence OTHER patterns to prevent misclassification - with enhanced excludes

        _Rule(DocumentType.UNKNOWN, "PAYMENT RECEIPT",      "PAYMENT RECEIPT", match="contains", scope="header_lines",
              exclude=("INVOICE", "CREDIT MEMO", "STATEMENT", "TOTAL DUE"), exclude_scope="header"),
        _Rule(DocumentType.UNKNOWN, "PACKING SLIP",         "PACKING SLIP", match="contains", scope="header_lines",
              exclude=("INVOICE", "CREDIT MEMO", "STATEMENT"), exclude_scope="header"),
        _Rule(DocumentType.UNKNOWN, "PROOF OF DELIVERY",    "PROOF OF DELIVERY", match="contains", scope="header_lines"),
        _Rule(DocumentType.UNKNOWN, "PROOF OF DELIVERY",    "PROOF OF DELIVERY", match="contains", scope="first_lines"),
        _Rule(DocumentType.UNKNOWN, "ORDER CONFIRMATION",   "ORDER CONFIRMATION", match="contains", scope="header_lines",
              exclude=("INVOICE", "CREDIT MEMO"), exclude_scope="header"),

        # -- Clear OTHER patterns (first 3 lines) --
        _Rule(DocumentType.UNKNOWN, "RECEIPT",               "RECEIPT header", exclude=("RECEIPT OF GOODS", "INVOICE", "CREDIT")),
        _Rule(DocumentType.UNKNOWN, "SALES ORDER",           "SALES ORDER header"),
        _Rule(DocumentType.UNKNOWN, "SUBMITTAL DATA",        "SUBMITTAL DATA header"),
        _Rule(DocumentType.UNKNOWN, "SHIPMENT CONFIRMATION", "SHIPMENT CONFIRMATION header"),
        _Rule(DocumentType.UNKNOWN, "MATERIAL RETURNED",     "MATERIAL RETURNED header"),
        _Rule(DocumentType.UNKNOWN, "BILL PAYMENT STUB",     "BILL PAYMENT STUB header"),
        _Rule(DocumentType.UNKNOWN, "CARD INFORMATION",      "CARD INFORMATION header"),
        _Rule(DocumentType.UNKNOWN, "ACKNOWLEDGEMENT",       "ACKNOWLEDGEMENT header", exclude=("TOTAL DUE",), exclude_scope="header"),

        # ==================== TIER 3: EXTENDED HEADER PATTERNS ====================
        # Medium-confidence patterns using extended scope

        # -- Vendor-Specific Statement Patterns (Must come before AF INVOICE) --
        _Rule(DocumentType.STATEMENT, "AF STATEMENT",      "AF STATEMENT", match="contains", scope="header_lines", confidence=0.95),

        # -- Vendor-Specific Invoice Patterns (Medium Confidence) --
        _Rule(DocumentType.INVOICE,   "AF INVOICE",        "AF INVOICE", match="contains", scope="header_lines", confidence=0.95),
        _Rule(DocumentType.INVOICE,   "THEPLUMBINGEXCHANGE", "PLUMBING EXCHANGE pattern", match="contains", scope="header_lines", confidence=0.95),
        _Rule(DocumentType.INVOICE,   r"PLUMBING\s*EXCHANGE[\s\S]*?INVOICE", "PLUMBING EXCHANGE INVOICE", match="regex", scope="full_header", confidence=0.95),
        _Rule(DocumentType.INVOICE,   "INVOICE I-",        "INVOICE pattern", match="contains", scope="header_lines", confidence=0.95),

        # -- Advanced Vendor-Specific Invoice Rules --
        _Rule(DocumentType.INVOICE,   r"SUPREME\s*PLUMBING[\s\S]*?INVOICE[\s\S]*?AMOUNT", "SUPREME PLUMBING INVOICE with AMOUNT", match="regex", scope="full_header", confidence=0.95),
        _Rule(DocumentType.INVOICE,   r"ACKNOWLEDGEMENT[\s\S]*?TOTAL\s*DUE", "ACKNOWLEDGEMENT with TOTAL DUE", match="regex", scope="full_header", confidence=0.95,
              exclude=("SALES ORDER", "PURCHASE ORDER")),

        # -- Vendor-Specific Credit Patterns (Medium Confidence) --
        _Rule(DocumentType.CREDIT,    "CUSTOMER CREDIT",   "CUSTOMER CREDIT pattern", match="contains", scope="header_lines", confidence=0.95),

        # -- Other Statement Patterns (Medium Confidence) --
        _Rule(DocumentType.STATEMENT, "STATEMENT",         "STATEMENT extended header", scope="header_lines", confidence=0.95),

        # ==================== TIER 4: BID DOCUMENTS ====================
        # Bid documents (must come before generic QUOTE/ESTIMATE rules)

        _Rule(DocumentType.BID, "BID PROPOSAL", "BID PROPOSAL header", match="contains", scope="header_lines", confidence=0.95),
        _Rule(DocumentType.BID, "BID NUMBER",   "BID NUMBER header",   match="contains", scope="header_lines", confidence=0.95),

        # ==================== TIER 5: ADDITIONAL OTHER PATTERNS ====================
        # Lower-priority OTHER patterns and vendor-specific exclusions

        # -- Purchase Order Patterns --
        _Rule(DocumentType.UNKNOWN, "PURCHASE ORDER",       "PURCHASE ORDER", scope="header_lines"),
        _Rule(DocumentType.UNKNOWN, "P.O.",                 "PURCHASE ORDER", match="contains", scope="header_lines"),
        _Rule(DocumentType.UNKNOWN, "PO #",                 "PURCHASE ORDER", match="contains", scope="header_lines"),
        _Rule(DocumentType.UNKNOWN, "PO ",                  "PURCHASE ORDER", scope="header_lines"),

        # -- Quote/Estimate Patterns --
        _Rule(DocumentType.UNKNOWN, "QUOTE",                "QUOTE/ESTIMATE", scope="header_lines"),
        _Rule(DocumentType.UNKNOWN, "ESTIMATE",             "QUOTE/ESTIMATE", scope="header_lines"),

        # -- Advanced OTHER Patterns --
        _Rule(DocumentType.UNKNOWN, "RECEIPT OF PAYMENT",   "RECEIPT OF PAYMENT", match="contains", scope="header_lines"),
        _Rule(DocumentType.UNKNOWN, "CHANGE ORDER",         "CHANGE ORDER", match="contains", scope="header_lines"),
        _Rule(DocumentType.UNKNOWN, "COPPER TUBING CONTRACT","COPPER TUBING CONTRACT", match="contains", scope="header_lines"),
        _Rule(DocumentType.UNKNOWN, "PAYMENT AMOUNT",       "PAYMENT RECEIPT (Payment Amount)", match="contains", scope="header_lines", confidence=0.95),

        # -- Vendor-Specific OTHER Exclusions --
        _Rule(DocumentType.UNKNOWN, r"SUPREME\s*PLUMBING[\s\S]*?SO-\d+", "SUPREME PLUMBING SO", match="regex", scope="full_header", confidence=0.95),
        _Rule(DocumentType.UNKNOWN, r"SUPREME\s*PLUMBING[\s\S]*?CO-\d+", "SUPREME PLUMBING CO", match="regex", scope="full_header", confidence=0.95),

        # -- Spaced Letter Patterns --
        _Rule(DocumentType.UNKNOWN, r'R\s+E\s+C\s+E\s+I\s+P\s+T\s+S', "Spaced CASH RECEIPTS", match="regex", scope="header_lines"),
        _Rule(DocumentType.UNKNOWN, r'P\s+A\s+Y\s+M\s+E\s+N\s+T', "Spaced CUSTOMER PAYMENT", match="regex", scope="header_lines"),

        # ==================== TIER 6: FALLBACK PATTERNS ====================
        # Low-confidence fallback patterns - use with caution

        _Rule(DocumentType.CREDIT,  "CREDIT",  "CREDIT fallback", match="contains", confidence=0.7,
              exclude=("CREDIT TERMS", "CREDIT LIMIT", "CREDIT CARD"), exclude_scope="header"),
        _Rule(DocumentType.INVOICE, "INVOICE", "INVOICE fallback", match="contains", scope="first_lines_rest", confidence=0.7),
    ]

    @classmethod
    def _read_first_page(cls, filename: str, pdf_bytes: Optional[bytes] = None) -> str:
        """Read text from only the first page of a PDF.

        Much faster than read_invoice() for multi-page documents because it
        avoids parsing pages 2..N that the classifier never looks at.

        Args:
            filename: Path to the PDF file (used when *pdf_bytes* is None).
            pdf_bytes: If provided, open the PDF from memory instead of disk.
        """
        open_kwargs = (
            {"stream": pdf_bytes, "filetype": "pdf"} if pdf_bytes is not None
            else {"filename": filename}
        )
        with fitz.open(**open_kwargs) as doc:
            if len(doc) == 0:
                return ""
            return doc[0].get_text()

    @classmethod
    def _extract_header_text(cls, filename: str, header_lines: int = 60, pdf_bytes: Optional[bytes] = None) -> str:
        """Extract text from just the header/top of a PDF for classification.

        Document type identification is most accurate when looking at document headers
        where titles like "INVOICE", "STATEMENT", "CREDIT MEMO" typically appear.

        Args:
            filename: Path to the PDF file
            header_lines: Number of lines from the top to extract (default: 60)
            pdf_bytes: If provided, open the PDF from memory instead of disk.

        Returns:
            str: Extracted header text, uppercase for matching
        """
        try:
            first_page_text = cls._read_first_page(filename, pdf_bytes=pdf_bytes)
            lines = first_page_text.split('\n')
            header_text = '\n'.join(lines[:header_lines])
            return header_text.upper()
        except Exception as e:
            logger.error(f"Error extracting header text from {filename}: {str(e)}")
            return ""

    @classmethod
    def _match_rules(
        cls,
        first_lines: list[str],
        header_lines: list[str],
        header_text: str,
    ) -> tuple[_Rule, str] | None:
        """Return the first matching ``(_Rule, matched_line)`` or ``None``."""
        scopes: dict[str, list[str]] = {
            "first_lines": first_lines,
            "first_lines_rest": first_lines[1:],
            "header_lines": header_lines,
            "full_header": [header_text],  # Full header text as single item for regex patterns
        }

        for rule in cls.RULES:
            for line in scopes[rule.scope]:
                if not cls._match_line_with_rule(rule, line):
                    continue
                if rule.exclude:
                    check = header_text if rule.exclude_scope == "header" else line
                    if any(ex in check for ex in rule.exclude):
                        continue
                return rule, line
        return None

    @classmethod
    def _match_line_with_rule(cls, rule: _Rule, line: str):
        """Check if line matches pattern based on match type."""
        if rule.match == "contains":
            return rule.pattern in line
        elif rule.match == "regex":
            return bool(re.search(rule.pattern, line))
        else:
            return line.startswith(rule.pattern)

    @classmethod
    def classify(cls, filename: str, text: str | None = None, pdf_bytes: Optional[bytes] = None) -> ClassificationResult:
        """Classify a PDF document type using precise header-based analysis.

        Args:
            filename: Path to the PDF file (used as label for logs when *pdf_bytes* is given)
            text: Pre-extracted PDF text. When provided, the first 60 lines are
                used directly and the file is not re-read from disk.
            pdf_bytes: If provided, open the PDF from memory instead of disk.

        Returns:
            ClassificationResult with doc_type, confidence, and details
        """
        # Reuse caller-provided text (e.g. raw_pdf_text from the extraction
        # pipeline) to avoid re-reading the PDF from disk.
        if text is not None:
            lines = text.split('\n')
            header_text = '\n'.join(lines[:HEADER_LINES_COUNT]).upper()
        else:
            header_text = cls._extract_header_text(filename, header_lines=HEADER_LINES_COUNT, pdf_bytes=pdf_bytes)

        if not header_text:
            logger.warning(f"No text extracted from {filename}, classifying as UNKNOWN")
            return ClassificationResult(DocumentType.UNKNOWN, 0.0, {'reason': 'no_text_extracted', 'first_line': ''})

        lines = header_text.split('\n')
        first_lines = [line.strip() for line in lines[:FIRST_LINES_COUNT] if line.strip()]
        header_lines = [line.strip() for line in lines[:HEADER_LINES_COUNT] if line.strip()]

        first_line = first_lines[0] if first_lines else ''
        classification_details: dict = {'first_line': first_line, 'header_lines': first_lines}

        result = cls._match_rules(first_lines, header_lines, header_text)
        if result is not None:
            rule, matched_line = result
            reason = (
                f"{rule.reason}: {matched_line}"
                if rule.reason == "INVOICE pattern"
                else rule.reason
            )

            # Enhanced logging with confidence and manual review flags
            confidence_label = "HIGH" if rule.confidence >= 0.95 else "MEDIUM" if rule.confidence >= 0.7 else "LOW"
            review_flag = " [MANUAL REVIEW RECOMMENDED]" if 0.7 <= rule.confidence < 0.95 else ""

            logger.info(f"Classified {filename} as {rule.doc_type.value} ({reason}) "
                       f"- Confidence: {confidence_label} ({rule.confidence:.2f}){review_flag}")

            return ClassificationResult(
                rule.doc_type,
                rule.confidence,
                {**classification_details, 'match_reason': reason, 'confidence_tier': confidence_label},
            )

        logger.info(f"Classified {filename} as UNKNOWN (no clear indicators found)")
        return ClassificationResult(DocumentType.UNKNOWN, 0.5, {**classification_details, 'match_reason': 'default fallback', 'confidence_tier': 'LOW'})

    @classmethod
    def get_classification_stats(cls) -> dict:
        """Return statistics about the classification rules for monitoring."""
        rule_counts = {}
        confidence_ranges = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}

        for rule in cls.RULES:
            rule_counts[rule.doc_type.value] = rule_counts.get(rule.doc_type.value, 0) + 1

            if rule.confidence >= 0.95:
                confidence_ranges["HIGH"] += 1
            elif rule.confidence >= 0.7:
                confidence_ranges["MEDIUM"] += 1
            else:
                confidence_ranges["LOW"] += 1

        return {
            "total_rules": len(cls.RULES),
            "rules_by_type": rule_counts,
            "rules_by_confidence": confidence_ranges,
            "high_confidence_threshold": 0.95,
            "medium_confidence_threshold": 0.7,
        }

    @classmethod
    def validate_classification_distribution(cls, results: list[ClassificationResult]) -> dict:
        """Analyze classification distribution to flag potential issues."""
        if not results:
            return {"warning": "No classification results provided"}

        total = len(results)
        distribution = {}
        confidence_distribution = {}
        manual_review_count = 0

        for result in results:
            # Document type distribution
            doc_type = result.doc_type.value
            distribution[doc_type] = distribution.get(doc_type, 0) + 1

            # Confidence distribution
            tier = result.details.get('confidence_tier', 'UNKNOWN')
            confidence_distribution[tier] = confidence_distribution.get(tier, 0) + 1

            # Manual review flag
            if result.requires_manual_review:
                manual_review_count += 1

        other_percentage = (distribution.get("UNKNOWN", 0) / total) * 100
        manual_review_percentage = (manual_review_count / total) * 100

        warnings = []
        if other_percentage > 50:
            warnings.append(f"High UNKNOWN classification rate: {other_percentage:.1f}% (threshold: 50%)")
        if manual_review_percentage > 20:
            warnings.append(f"High manual review rate: {manual_review_percentage:.1f}% (threshold: 20%)")

        return {
            "total_classified": total,
            "distribution": distribution,
            "distribution_percentages": {k: (v/total)*100 for k, v in distribution.items()},
            "confidence_distribution": confidence_distribution,
            "manual_review_count": manual_review_count,
            "manual_review_percentage": manual_review_percentage,
            "warnings": warnings,
        }

