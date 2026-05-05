{% macro should_include_sheet(column_name) %}
    {#
       Filters out sheet names based on the skip_sheets variable.
       Returns a boolean expression that is TRUE for sheets we WANT to keep.

       NULL handling: a NULL sheet name means "no sheet assigned" (e.g. unmapped
       invoice items). We treat NULL as keep, because `NULL NOT LIKE 'anything'`
       evaluates to NULL (falsy in WHERE) and would otherwise silently drop these
       rows from the timeline / history.
    #}
    {% set sheets = var('skip_sheets', '').replace('"', '').split(',') | map('trim') | reject('eq', '') | list %}
    {% if sheets | length == 0 %}
        TRUE
    {% else %}
    (
        {{ column_name }} IS NULL
        OR (
        {% for sheet in sheets %}
            {{ column_name }} NOT LIKE '%{{ sheet }}%'
            {% if not loop.last %} AND {% endif %}
        {% endfor %}
        )
    )
    {% endif %}
{% endmacro %}
