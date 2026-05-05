# ADR-0010: Email-Derived Vendor Identification

## Status

ACCEPTED (Implemented)

## Date

2026-01-20

## Context

Vendor identification was originally performed by:
1. A static `INVOICE_SENDER` list hardcoded in Python
2. OCR-based vendor name extraction from PDF content

Both approaches were unreliable:
- The static list required code changes for new vendors
- OCR often misread vendor names (non-ASCII characters, poor scan quality)
- Forwarded invoices lost the original sender context
- Different email addresses from the same vendor caused mismatches

## Decision

Replace vendor identification with an **email-derived approach** using a database-driven table.


### Vendor Resolution Logic

1. Extract sender email from the email message
2. Look up sender_email in EmailVendorMapping table
3. If match found --> use vendor_name from database
4. If no match --> extract vendor from email subject (for forwarded invoices)
5. If still no match --> assign "Unknown" vendor as fallback

### Forwarded Invoice Handling

For invoices forwarded from a shared mailbox:
- Parse the email subject line for vendor indicators
- Use pattern: extract vendor from subject when sender is a forwarder

### Fallback Strategy

- `email_derived_vendor` is NEVER null. If all resolution fails, the value is "Unknown" vendor. This prevents null propagation through the pipeline.

## Consequences

### Positive
- New vendors added via database insert (no code deployment needed)
- More reliable than OCR (email sender is deterministic)
- Eliminates a class of extraction errors (misread vendor names)
- Database-driven mapping is auditable and version-trackable
- "Unknown" vendor fallback prevents null-related failures downstream

### Negative
- Requires maintaining the email to vendor mapping table
- Forwarded invoices still require heuristic parsing of subject lines
- Email sender changes (e.g., vendor switches email provider) require table updates


## Compliance
- Vendor identification in new extraction code MUST use `email_derived_vendor` from the email pipeline
- OCR-based vendor extraction is deprecated and should not be used for primary vendor assignment

## Notes
