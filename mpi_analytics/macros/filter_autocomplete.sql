{#
    Macro: filter_autocomplete_union_blocks

    Purpose: Generate UNION ALL blocks for filter autocomplete materialized view

    Parameters:
        - columns: List of column names from source table (e.g., ['item', 'vendor', 'class_'])
        - source_ref: dbt ref() to source model (default: 'stg__invoice_items')
        - include_date_range: Whether to include first_seen_date/last_seen_date (default: true)

    Returns:
        SQL string with UNION ALL blocks for each column

    Example Usage:
        {{ filter_autocomplete_union_blocks(
            columns=['item', 'vendor', 'description'],
            source_ref='stg__invoice_items',
            include_date_range=true
        ) }}
#}

{% macro filter_autocomplete_union_blocks(columns, source_ref='stg__invoice_items', include_date_range=true) %}

{% for column in columns %}
    -- {{ column | replace('_', ' ') | title }} column
    SELECT
        '{{ column }}' as column_name,
        {{ column }} as original_value,
        LOWER({{ column }}) as normalized_value
        {%- if include_date_range -%}
            ,
            MIN(date) as first_seen_date,
            MAX(date) as last_seen_date
        {%- endif %}
    FROM {{ ref(source_ref) }}
    WHERE {{ column }} IS NOT NULL AND {{ column }} != ''
    GROUP BY {{ column }}

    {%- if not loop.last %}

    UNION ALL

    {% endif -%}
{% endfor %}

{% endmacro %}
