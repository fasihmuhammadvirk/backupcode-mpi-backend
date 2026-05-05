# ADR-0009: Declarative Classification Rules

## Status

ACCEPTED (Implemented)

## Date

2026-01-15

## Context

Document classification (determining whether a PDF is an invoice, credit memo, statement, or unsupported document) was implemented as a series of hardcoded `if/elif/else` branches in the `document_classifier` module.
Each new document type or classification rule required modifying the function body, increasing cyclomatic complexity and making the logic difficult to test or extend.

Similarly, item classification (mapping items to QuickBooks accounts) used a 4-level priority system with nested conditionals that were hard to reason about.

## Decision

Replace hardcoded classification branches with a **declarative RULES list** pattern. Classification logic is defined as data, not code.

### Evaluation Strategy

1. Rules are evaluated in waterfall (top rules have higher priority)
2. First matching rule determines the classification
3. If no rule matches, document is classified as "other"
4. The classifying method uses the document's text content (not just filename/metadata)

## Consequences

### Positive
- New document types added by appending to the RULES list (no function modification)
- Rules are independently testable (pass text, assert classification)
- Priority ordering is explicit and visible
- Classification logic is auditable (the RULES list IS the specification)
- Easier for developers to understand and modify

### Negative
- Rules can become complex if not kept simple
- Priority conflicts must be manually managed (no automatic conflict detection)
- Some rules require access to both `text` and `metadata`, increasing the match function signature

## Compliance
- New classification logic MUST be added as a rule in the RULES list
- Hardcoded `if/elif` branches for classification are not permitted in new code

## Notes
