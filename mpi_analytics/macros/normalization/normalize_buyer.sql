{% macro create_normalize_buyer_function() %}
    CREATE OR REPLACE FUNCTION normalize_buyer_fn(buyer_name TEXT)
    RETURNS TEXT AS $$
    DECLARE
        cleaned TEXT;
        alpha_part TEXT := '';
        numeric_part TEXT := '';
        result TEXT := '';
    BEGIN
        IF buyer_name IS NULL OR TRIM(buyer_name) = '' THEN
            RETURN buyer_name;
        END IF;

        -- Step 1: Remove ALL non-alphanumeric characters (including spaces, dots, parentheses, dashes)
        -- Examples:
        --   "(718) 536-4610" -> "7185364610"
        --   ". 1 3 47 7 0 6 97 4 6" -> "13477069746"
        --   "AL EX 20 3- 4 40 - 60 96" -> "Alex 2034406096"
        cleaned := REGEXP_REPLACE(buyer_name, '[^A-Za-z0-9]', '', 'g');

        -- Step 2: Extract alphabetic characters (no spaces) and numeric part (all digits together)
        alpha_part := REGEXP_REPLACE(cleaned, '[^A-Za-z]', '', 'g');
        numeric_part := REGEXP_REPLACE(cleaned, '[^0-9]', '', 'g');

        -- Step 3: Format as Title Case "Alphabetic Numeric" with ONE space separator
        IF alpha_part != '' AND numeric_part != '' THEN
            result := INITCAP(alpha_part) || ' ' || numeric_part;
        ELSIF alpha_part != '' THEN
            result := INITCAP(alpha_part);
        ELSIF numeric_part != '' THEN
            result := numeric_part;
        ELSE
            result := '';
        END IF;

        RETURN result;
    END;
    $$ LANGUAGE plpgsql IMMUTABLE;
{% endmacro %}

{% macro normalize_buyer(buyer_column) %}
    normalize_buyer_fn({{ buyer_column }})
{% endmacro %}

