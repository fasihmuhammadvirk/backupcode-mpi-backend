-- PROBABLY WANT THIS TO BE PULLED FROM THE DB INSTEAD
{% macro add_vendor_suffix(item_column, vendor_column) %}
    -- Add suffix based on vendor name matching
    CASE
        -- Match vendor name patterns (case-insensitive, ordered by specificity)
        WHEN UPPER({{ vendor_column }}) LIKE '%BMW%' THEN {{item_column}} || '-B'
        WHEN UPPER({{ vendor_column }}) LIKE '%WORLD WIDE%' OR UPPER({{ vendor_column }}) LIKE '%WWPS%' THEN {{item_column}} || '-W'
        WHEN UPPER({{ vendor_column }}) LIKE '%Y & S%' OR UPPER({{ vendor_column }}) LIKE '%Y&S%' THEN {{item_column}} || '-Y'
        WHEN UPPER({{ vendor_column }}) LIKE '%SUPREME%' THEN {{item_column}} || '-S'
        WHEN UPPER({{ vendor_column }}) LIKE '%PYRAMID%' THEN {{item_column}} || '-P'
        WHEN UPPER({{ vendor_column }}) LIKE '%PARK%' AND UPPER({{ vendor_column }}) NOT LIKE '%CENTRAL PARK%' THEN {{item_column}} || '-PA'
        WHEN UPPER({{ vendor_column }}) LIKE '%GOTHAM%' THEN {{item_column}} || '-G'
        WHEN UPPER({{ vendor_column }}) LIKE '%FW WEBB%' OR UPPER({{ vendor_column }}) LIKE '%F.W. WEBB%' THEN {{item_column}} || '-F'
        WHEN UPPER({{ vendor_column }}) LIKE '%FLOW MARK%' OR UPPER({{ vendor_column }}) LIKE '%FLOWMARK%' THEN {{item_column}} || '-F'
        WHEN UPPER({{ vendor_column }}) LIKE '%ABC OPUS%' THEN {{item_column}} || '-A'
        WHEN UPPER({{ vendor_column }}) LIKE '%AF SUPPLY%' THEN {{item_column}} || '-A'
        WHEN UPPER({{ vendor_column }}) LIKE '%BRUCE%' THEN {{item_column}} || '-BR'
        WHEN UPPER({{ vendor_column }}) LIKE '%PLUMBING EXCHANGE%' THEN {{item_column}} || '-PE'
        -- No suffix for unrecognized vendors, return the same values
        ELSE {{item_column}}
    END
{% endmacro %}
