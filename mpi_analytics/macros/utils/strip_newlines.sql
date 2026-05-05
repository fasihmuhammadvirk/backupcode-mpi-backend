{% macro strip_newlines(column) %}
    TRIM(REPLACE(REPLACE(REPLACE({{ column }}, chr(9), ' '), chr(10), ' '), chr(13), ' '))
{% endmacro %}
