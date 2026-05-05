{% macro resolve_temp_mpi_item(sheet_name_column) %}
{#
    Resolves the MPI item code for temporary mappings based on sheet name.

    Maps sheet names to account types using the sheet_account_mapping seed table:
    - E (Equipment sheets) -> 'UIDI - Job Equipment'
    - M (Materials sheets) -> 'UIDI - Job Materials Purchased'
    - Other/Unknown -> 'UIDI-' || sheet_name (fallback)

    Normalizes sheet names by:
    - Replacing ") (" with " - "
    - Removing remaining parentheses
    - Converting to uppercase

    The mapping is maintained in seeds/sheet_account_mapping.csv for easy updates.

    Usage:
        {{ resolve_temp_mpi_item('temp_sheet_name') }}
#}
COALESCE(
    (
        SELECT mpi_item_template
        FROM {{ ref('sheet_account_mapping') }}
        WHERE sheet_name = UPPER({{ normalize_sheet_name(sheet_name_column) }})
    ),
    'UIDI-' || COALESCE({{ sheet_name_column }}, 'UNKNOWN')
)
{% endmacro %}
