-- See safe_cast.yml for documentation
{% macro safe_cast(field_to_cast, type_to_cast_to) %}

    {% set clean_field = "REPLACE(" ~ field_to_cast ~ ", ',', '')" %}

    CASE
        -- Check if the field is not null, not empty, has reasonable length, and matches numeric pattern
        -- This replicates the logic from InvoiceItems._safe_numeric_cast in Python:
        -- - Removes commas
        -- - Validates with a regex so bad rows don't crash the query
        -- - Returns NULL when non-numeric so comparisons behave as expected
        -- - Limits length to prevent extremely long strings from causing issues
        WHEN {{ field_to_cast }} IS NOT NULL
            AND {{ field_to_cast }} != ''
            AND LENGTH({{ field_to_cast }}) < 100
            AND {{ clean_field }} ~ '^-?[0-9]*\.?[0-9]+$'
        THEN
            -- Cast to target type
            ({{ clean_field }}::{{ type_to_cast_to }})
        ELSE
            -- Return NULL for invalid values
            NULL
    END

{% endmacro %}
