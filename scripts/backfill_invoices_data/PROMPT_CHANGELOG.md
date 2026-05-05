# Prompt Schema Changelog

Track prompt versions and their associated content hashes.

| Version | Hash | Date       | Description                                                                                                                         |
|---------|------|------------|-------------------------------------------------------------------------------------------------------------------------------------|
| v17.0   | 4e8a19f7836e | 2026-03-20 | (WIP) Unified DocumentType enum (shared module), enriched doc_type schema descriptions, per-page classification prompt, STATEMENT/BID added to Gemini enum |
| v13.0   | c35eef19bb92 | 2026-01-23 | Updated to reduce Common OCR errors. Flowmark MPN issue and BMW out_of_stock_number/item_code issue                                 |
| v12.0   | c35eef19bb92 | 2026-01-14 | Make all fields strings to avoid floating point errors in fields like amount, cost                                                  |
| v11.0   | 5720271c5eaf | 2026-01-14 | Fixed schema validation issues: added outOfStock field to Pydantic schema, numeric fields are string (remove floating point errors) |
| v10.0   | e94029716901 | 2026-01-12 | Initial tracked version with doc_type field                                                                                         |

## How to Update

1. Modify schema in `prompt_schemas.py`
2. Run extraction - you'll see a warning with the new hash
3. Bump `PROMPT_VERSION` (e.g., "v10.0" -> "v10.1")
4. Update `KNOWN_HASH` with the new hash from the warning
5. Add entry to this changelog
