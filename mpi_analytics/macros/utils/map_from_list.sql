{% macro map_from_lists(column_name, canonical_map, precomputed_column=none) %}
    {#- When precomputed_column is provided, use it for the WHEN comparisons to avoid
        re-evaluating expensive expressions (like normalize_address_fn) per WHEN clause.
        The raw column_name is still used in the ELSE to preserve the original return type. -#}
    {%- set compare_expr = precomputed_column if precomputed_column else column_name -%}
    case
        {% for good_value, bad_values in canonical_map.items() %}
            when lower({{ compare_expr }}) in (
                {% for bad in bad_values %}
                    lower('{{ bad }}'){% if not loop.last %}, {% endif %}
                {% endfor %}
            )
            then '{{ good_value }}'
        {% endfor %}
        else {{ column_name }}
    end
{% endmacro %}
