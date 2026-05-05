# MPI Analytics

# Getting started
1. Make sure you have dbt installed (should be from requirements.txt)
2. To install dependencies: `python run_dbt.py deps`
3. To run the existing models: `python run_dbt.py`
4. To run a specific model: `python run_dbt.py run -s int__my_model`


# Guidelines
We create models in the following order:
1. Staging models (named `stg__<model_name>`)
2. Intermediate models (named `int__<model_name>`)
3. Marts model (named `mart__<model_name>`)

# File Organization
Here's the current recommend structure for file organization:
```
models/
  sources/              -- TODO: where we _want_ the extractor to write to. Right now its where we bring data from public
  staging/
    pdf_raw/            -- the table where we mirror the source with minimal cleaning (like trimming text, cast types)
  intermediate/
    pdf_normalized/     -- normalize fields, text, dedupe, fix dates, etc
    pdf_enriched/       -- add more context from the PDF that was missing
  marts/                -- TODO: where we store dims and facts. Right now we only have one type: "mart"
    pdf_main/           -- the "big table" that holds all of the clean data
    analysis_page/      -- the table with data for the Analysis Page
    create_po_page/     -- the table with data for the Create PO Page
    filters/            -- tables that are used for filtering
macros/
  normalization/        -- macros that help with normalization
  utils/                -- any helper macros
```

- Each model has its own folder and a group of models can be grouped into a folder depending on their logic.
- Each model has its own `yml` file that must follow the name of the sql. eg: `int__my_model.sql`, `int__my_model.yml`
- The staging model is only to bring in the raw data.
- The intermediate is where transformations happen.
- The marts are what are produced for the backend/frontend to use.

# Incremental Models

Several models use **incremental materialization** (`merge` strategy) to avoid reprocessing all 285k+ rows on every run. Only new or changed rows are processed, reducing run time from ~95s (full refresh) to ~25s.

## Which models are incremental?

| Model | Unique Key | What triggers re-processing |
|-------|------------|-----------------------------|
| `stg__extracted_global_fields` | `extraction_invoice_id` | New extractions in `raw.model_extracted_data` |
| `stg__extracted_line_items` | `line_item_id` | New extractions in `raw.model_extracted_data` |
| `int__invoice_items_mapped` | `invoice_items_id` | New invoices (`date_added`), mapping changes (`extraction_timestamp`) |
| `int__invoice_items_with_normalized_fields` | `invoice_items_id` | Upstream changes (`_dbt_updated_at`), user override add/update/remove |
| `mart__invoice_items` | `invoice_items_id` | Upstream changes (`_dbt_updated_at`) |
| `mart__invoice_items_map` | `id` | Upstream changes (`_dbt_updated_at`) |

## How re-extractions are handled

When an invoice PDF is re-extracted, it gets a new `extraction_id`, which produces new `invoice_items_id` hashes. The old IDs become orphans in incremental tables. This is handled by a **three-level deduplication cascade**:

1. **Staging post-hook DELETE**: Physically removes old extraction rows when a newer extraction exists for the same file (`s3_file_key`).
2. **Compat view DENSE_RANK**: Keeps only the latest extraction per logical invoice (`vendor + ref_no + date`).
3. **Incremental post-hook DELETEs**: Each incremental table has a post-hook that removes rows whose `invoice_items_id` no longer exists in its upstream source. This cascades: `mapped → normalized → marts`.

## Full refresh

To rebuild all tables from scratch (e.g., after schema changes or for periodic reconciliation):
```bash
python run_dbt.py run --full-refresh
```

## Other marts (full-refresh tables)

These marts are **not** incremental because they perform aggregations that require the full dataset:
- `mart__address_sheet_aggregates`
- `mart__item_price_comparison`
- `mart__price_increases`
- `mart__mapping_audit`
- `mart__item_mapping_timeline`
- `mart__unmapped_report`
