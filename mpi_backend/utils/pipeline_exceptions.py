"""
Pipeline Operations Exceptions - Structured error types for pipeline operations.

Extracted from routes/extraction_queue.py to follow ADR-0012 (thin routes).
"""

from typing import Optional


class PipelineOperationError(Exception):
    """Base exception for pipeline operations"""
    def __init__(self, message: str, error_code: Optional[str] = None, details: Optional[dict] = None):
        self.message = message
        self.error_code = error_code or "PIPELINE_ERROR"
        self.details = details or {}
        super().__init__(message)


class GmailCircuitBreakerError(PipelineOperationError):
    """Gmail API circuit breaker is open"""
    def __init__(self, retry_after: int = 300):
        super().__init__(
            "Gmail API is temporarily unavailable due to rate limits",
            "GMAIL_CIRCUIT_BREAKER_OPEN",
            {"retry_after": retry_after}
        )


class ScanRateLimitError(PipelineOperationError):
    """User has exceeded scan rate limit"""
    def __init__(self, retry_after: int):
        super().__init__(
            f"Scan rate limit exceeded. Retry after {retry_after} seconds",
            "SCAN_RATE_LIMIT_EXCEEDED",
            {"retry_after": retry_after}
        )


class ValidationScoreError(PipelineOperationError):
    """Invalid validation score threshold"""
    def __init__(self, score: float):
        super().__init__(
            f"Validation score {score} must be between 0 and 100",
            "INVALID_VALIDATION_SCORE",
            {"provided_score": score}
        )
