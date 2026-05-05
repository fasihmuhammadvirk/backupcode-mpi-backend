{#
    Macro: unnest_invoices

    Purpose: Normalize multi-invoice and single-invoice PDFs into one row per invoice.
    Encapsulates the shared invoice_array / invoices_unnested CTE logic used by
    both stg__extracted_global_fields and stg__extracted_line_items.

    Parameters:
        - source_cte: Name of the upstream CTE that supplies the rows
                      (must include a `raw_data` JSONB column).
        - filter_line_items: When true, filters out invoices whose line_items
                             array is NULL or empty.  (default: false)
        - filter_non_invoices: When true, keeps only invoice-like doc_types
                               (INVOICE, CREDIT, CREDIT_MEMO, BID) or NULL.
                               NULL is kept for backwards compat with old
                               extractions that predate the doc_type field.
                               Allowed types mirror DocumentType.is_invoice_like.
                               (default: false)

    Outputs two CTEs:
        - invoice_array   -- adds `invoices_arr` column
        - invoices_unnested -- one row per invoice with `invoice_obj` and `invoice_index`

    Example Usage:
        WITH source AS ( ... ),
        latest_extractions AS ( ... ),
        {{ unnest_invoices('latest_extractions', filter_non_invoices=true) }}
        SELECT ... FROM invoices_unnested
#}

{% macro unnest_invoices(source_cte, filter_line_items=false, filter_non_invoices=false) %}

-- Normalize: if 'invoices' key exists, use it; otherwise wrap root in a 1-element array
invoice_array AS (
    SELECT
        *,
        CASE
            WHEN raw_data ? 'invoices' THEN raw_data->'invoices'
            ELSE jsonb_build_array(raw_data)
        END AS invoices_arr
    FROM {{ source_cte }}
),

invoices_unnested AS (
    SELECT
        ia.*,
        inv.invoice_obj,
        inv.invoice_index::int AS invoice_index
    FROM invoice_array ia,
    LATERAL jsonb_array_elements(ia.invoices_arr)
        WITH ORDINALITY AS inv(invoice_obj, invoice_index)
    {% if filter_line_items or filter_non_invoices %}
    WHERE 1=1
      {% if filter_line_items %}
      AND inv.invoice_obj->'line_items' IS NOT NULL
      AND jsonb_array_length(inv.invoice_obj->'line_items') > 0
      {% endif %}
      {% if filter_non_invoices %}
      AND (
          inv.invoice_obj->>'doc_type' IS NULL
          OR inv.invoice_obj->>'doc_type' IN ('INVOICE', 'CREDIT', 'CREDIT_MEMO', 'BID')
      )
      {% endif %}
    {% endif %}
)

{% endmacro %}
