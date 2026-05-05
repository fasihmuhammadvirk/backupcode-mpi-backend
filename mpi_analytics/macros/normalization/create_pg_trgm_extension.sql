{% macro create_pg_trgm_extension() %}
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
{% endmacro %}
