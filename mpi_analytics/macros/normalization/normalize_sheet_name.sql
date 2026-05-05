-- See normalize_sheet_name.yml for documentation

{% macro normalize_sheet_name(sheet_name_column) %}
{#
    Normalizes sheet name format by removing parentheses and periods,
    replacing ") (" patterns with dash for consistency.

    Normalization steps:
    1. Replace ") (" with " - " (converts "(BLACK MALLEABLE) (GAS)" to "BLACK MALLEABLE - GAS")
    2. Remove remaining parentheses
    3. Remove periods
    4. Collapse multiple spaces to single space and trim
    5. Handle NULL/empty values by returning 'NO SHEET NAME'

    Examples:
      - "(AIR FITTINGS)" -> "AIR FITTINGS"
      - "(BLACK MALLEABLE) (GAS)" -> "BLACK MALLEABLE - GAS"
      - NULL or "" -> "NO SHEET NAME"

    Usage:
        {{ normalize_sheet_name('m.resolved_sheet_name') }}
        {{ normalize_sheet_name('temp_sheet_name') }}
#}
CASE
    WHEN {{ sheet_name_column }} IS NULL OR TRIM({{ sheet_name_column }}) = ''
    THEN 'NO SHEET NAME'
    ELSE TRIM(
        REGEXP_REPLACE(
            REGEXP_REPLACE(
                REGEXP_REPLACE(
                    REGEXP_REPLACE({{ sheet_name_column }}, '\)\s*\(', ' - ', 'g'),
                    '[()]', '', 'g'
                ),
                '\.', '', 'g'
            ),
            '\s+', ' ', 'g'
        )
    )
END
{% endmacro %}
