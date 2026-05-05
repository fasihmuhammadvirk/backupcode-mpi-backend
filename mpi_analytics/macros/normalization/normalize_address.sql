-- See normalize_address.yml for documentation

{% macro create_normalize_address_function() %}
    CREATE OR REPLACE FUNCTION normalize_address_fn(addr TEXT)
    RETURNS TEXT AS $$
    BEGIN
        -- Return NULL/empty as-is
        IF addr IS NULL OR TRIM(addr) = '' THEN
            RETURN addr;
        END IF;

        -- Trim whitespace and apply title case
        addr := INITCAP(TRIM(addr));

        -- Fix business/legal terms that should remain uppercase
        addr := REGEXP_REPLACE(addr, '\yLlc\y', 'LLC', 'g');
        addr := REGEXP_REPLACE(addr, '\yLlp\y', 'LLP', 'g');
        addr := REGEXP_REPLACE(addr, '\yLp\y', 'LP', 'g');
        addr := REGEXP_REPLACE(addr, '\yInc\y', 'Inc.', 'g');
        addr := REGEXP_REPLACE(addr, '\yCorp\y', 'Corp.', 'g');
        addr := REGEXP_REPLACE(addr, '\yUsa\y', 'USA', 'g');
        addr := REGEXP_REPLACE(addr, '\yNyc\y', 'NYC', 'g');

        -- Normalize multiple spaces to single space
        addr := REGEXP_REPLACE(addr, '\s+', ' ', 'g');

        -- Expand cardinal directions: N/N. → North, S/S. → South, etc.
        addr := REGEXP_REPLACE(addr, '\yN\.?\y', 'North', 'g');
        addr := REGEXP_REPLACE(addr, '\yS\.?\y', 'South', 'g');
        addr := REGEXP_REPLACE(addr, '\yE\.?\y', 'East', 'g');
        addr := REGEXP_REPLACE(addr, '\yW\.?\y', 'West', 'g');

        -- normalize Street: handles "Street", "St", "St.", "St,"
        addr := REPLACE(addr, ' Street', ' St.');
        addr := REGEXP_REPLACE(addr, ' St\.?,?(\s|$)', ' St.\1', 'g');

        -- normalize Avenue: handles "Avenue", "Ave", "Ave.", "Ave,"
        addr := REPLACE(addr, ' Avenue', ' Ave.');
        addr := REGEXP_REPLACE(addr, ' Ave\.?,?(\s|$)', ' Ave.\1', 'g');

        -- normalize Road: handles "Road", "Rd", "Rd.", "Rd,"
        addr := REPLACE(addr, ' Road', ' Rd.');
        addr := REGEXP_REPLACE(addr, ' Rd\.?,?(\s|$)', ' Rd.\1', 'g');

        -- normalize Boulevard
        addr := REPLACE(addr, ' Boulevard', ' Blvd.');
        addr := REGEXP_REPLACE(addr, ' Blvd\.?,?(\s|$)', ' Blvd.\1', 'g');

        -- normalize Drive
        addr := REPLACE(addr, ' Drive', ' Dr.');
        addr := REGEXP_REPLACE(addr, ' Dr\.?,?(\s|$)', ' Dr.\1', 'g');

        -- normalize Lane
        addr := REPLACE(addr, ' Lane', ' Ln.');
        addr := REGEXP_REPLACE(addr, ' Ln\.?,?(\s|$)', ' Ln.\1', 'g');

        -- normalize Court
        addr := REPLACE(addr, ' Court', ' Ct.');
        addr := REGEXP_REPLACE(addr, ' Ct\.?,?(\s|$)', ' Ct.\1', 'g');

        -- normalize Place
        addr := REPLACE(addr, ' Place', ' Pl.');
        addr := REGEXP_REPLACE(addr, ' Pl\.?,?(\s|$)', ' Pl.\1', 'g');

        -- Remove any remaining trailing commas
        addr := REGEXP_REPLACE(addr, ',$', '');

        -- Final trim
        addr := TRIM(addr);

        RETURN addr;
    END;
    $$ LANGUAGE plpgsql IMMUTABLE;
{% endmacro %}

{% macro normalize_address(address_column, precomputed_column=none) %}
    {#- When precomputed_column is provided (a column already containing
        normalize_address_fn output), the WHEN comparisons use it directly,
        avoiding 17× redundant function calls per row. -#}
    {{ map_from_lists(
        precomputed_column if precomputed_column else ('normalize_address_fn(' ~ address_column ~ ')'),
        address_typo_map(),
        precomputed_column=precomputed_column
    ) }}
{% endmacro %}
