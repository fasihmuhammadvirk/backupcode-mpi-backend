# ADR-0008: Prompt Engineering Framework for Invoice Extraction

## Status

ACCEPTED (Implemented)

## Date

2026-01-01

## Context

Invoice data extraction from PDFs is the foundational step of the entire pipeline. Initially, a single hardcoded prompt was used for all invoice types. As the system encountered more suppliers, document formats, and edge cases, the prompt needed constant modification -- but each change risked regressing accuracy on previously-working document types.

Problems with the single-prompt approach:
- No way to measure accuracy before deploying a prompt change
- Credit memos, multi-invoice PDFs, and forwarded invoices needed different prompts
- No A/B testing capability (only "ship it and hope")
- Prompt changes were invisible in version control (embedded in function bodies)

## Decision

Build a **Prompt Optimizer framework** that treats prompts as versioned, testable artifacts.

### Components

1. **Prompt Templates** -- Named, versioned prompt strings stored as separate concerns. Examples:
   - `baseline` -- Standard single-invoice extraction
   - `multi_invoice` -- Handles PDFs containing multiple invoices
   - `supplier_aware` -- Includes supplier-specific context in the prompt

2. **PromptOptimizer** -- A CLI tool that runs multiple prompts against a batch of PDFs
   - Accepts a directory of PDFs or streams from S3
   - Runs each prompt variant against each PDF
   - Collects structured output from the AI model
   - Computes field-level accuracy scores

3. **Scorecard System** -- Quantitative evaluation of extraction quality
   - Field-level accuracy (date, vendor, ref_no, line items, totals)
   - Validation score threshold (raised from 80 to 95)
   - Side-by-side comparison of prompt variants

4. **Fuzzy Correction Layers** -- Post-extraction cleanup
   - Non-ASCII character normalization (lookalike chars causing mapping failures)
   - Header field fuzzy correction (date formats, vendor name variants)
   - `T` suffix handling for taxable amounts
   - Underscore escaping for literal matching

### Pipeline Integration

1. PDF is fetched from S3
2. Document Classifier (ADR-0009 rules) determines the document type
3. The appropriate prompt template is selected based on classification
4. The AI model (Gemini) extracts data using the selected prompt
5. Extraction is validated against the scorecard
6. Fuzzy correction layer cleans up systematic errors
7. Result is written to `raw.model_extracted_data` (ADR-0006)

### Performance Optimizations

- PDFs streamed from S3 in-memory (no temp disk I/O)
- `ThreadPoolExecutor` for parallel S3 download + classification
- `--workers` flag for configurable parallelism
- `--pdf-dir` optional (can also accept individual files)

## Consequences

### Positive
- Prompt changes are measurable before deployment (scorecard comparison)
- Different document types get specialized prompts (higher accuracy)
- Regression detection: run new prompt against the same test set
- Prompt templates are version-controlled alongside code
- Fuzzy correction catches systematic AI model errors

### Negative
- Multiple prompt templates increase maintenance surface
- Scorecard evaluation requires a labeled test set (manual effort to create)
- Parallel execution adds complexity to error handling and logging

### Quality Gates
- New prompts must score >= 95 validation score on the test set before deployment
- Regression: if any field accuracy drops >2% vs current production prompt, the change is blocked
- All prompt changes must include scorecard comparison in the PR

## Compliance
- New prompt changes MUST be evaluated via PromptOptimizer with scorecard comparison against the current production prompt
- Prompt templates are stored as named constants, not inline strings in function bodies

## Notes
