{#
    Macro: snapshot_marts / diff_mart

    Two-step workflow for comparing mart state before/after a pipeline change.

    Step 1 - Snapshot current state:
        dbt run-operation snapshot_marts

    Step 2 - Run your pipeline changes:
        dbt run --full-refresh --threads 12

    Step 3 - Diff a specific mart:
        dbt run-operation diff_mart --args '{mart: mart__invoice_items}'

    Step 4 - Cleanup when done:
        dbt run-operation cleanup_mart_snapshots

    Snapshots go into analytics._before_<mart_name> tables.
#}

{% macro snapshot_marts() %}
    {% set marts = [
        'mart__invoice_items',
        'mart__invoice_items_map',
        'mart__unmapped_report',
        'mart__price_increases',
        'mart__address_sheet_aggregates',
        'mart__mapping_audit',
        'mart__item_mapping_timeline',
        'mart__item_price_comparison',
    ] %}

    {% for mart in marts %}
        {% set snap_table = '_before_' ~ mart %}
        {% set drop_sql %}
            DROP TABLE IF EXISTS analytics.{{ snap_table }}
        {% endset %}
        {% set create_sql %}
            CREATE TABLE analytics.{{ snap_table }} AS
            SELECT * FROM analytics.{{ mart }}
        {% endset %}

        {{ log("Snapshotting analytics." ~ mart ~ " -> analytics." ~ snap_table, info=True) }}
        {% do run_query(drop_sql) %}
        {% do run_query(create_sql) %}
        {{ log("  [OK] " ~ snap_table, info=True) }}
    {% endfor %}

    {{ log("All mart snapshots created.", info=True) }}
{% endmacro %}


{% macro diff_mart(mart) %}
    {#
        Compare the current mart against its _before snapshot using audit_helper.
        Shows: in_a_only (removed), in_b_only (added), identical, modified counts
        plus the actual differing rows.

        Usage:
            dbt run-operation diff_mart --args '{mart: mart__invoice_items}'
    #}
    {% set primary_keys = {
        'mart__invoice_items':             'invoice_items_id',
        'mart__invoice_items_map':         'id',
        'mart__unmapped_report':           'report_id',
        'mart__price_increases':           'invoice_items_id',
        'mart__address_sheet_aggregates':  'customer_job',
        'mart__mapping_audit':             'audit_id',
        'mart__item_mapping_timeline':     'id',
        'mart__item_price_comparison':     'invoice_items_id',
    } %}

    {% set pk = primary_keys.get(mart) %}
    {% if not pk %}
        {{ exceptions.raise_compiler_error("Unknown mart: " ~ mart ~ ". Expected one of: " ~ primary_keys.keys() | list | join(', ')) }}
    {% endif %}

    {% set before_relation = adapter.get_relation(
        database=target.dbname,
        schema='analytics',
        identifier='_before_' ~ mart
    ) %}

    {% if not before_relation %}
        {{ exceptions.raise_compiler_error(
            "Snapshot table analytics._before_" ~ mart ~ " not found. Run `dbt run-operation snapshot_marts` first."
        ) }}
    {% endif %}

    {% set current_relation = adapter.get_relation(
        database=target.dbname,
        schema='analytics',
        identifier=mart
    ) %}

    {% if not current_relation %}
        {{ exceptions.raise_compiler_error(
            "Current table analytics." ~ mart ~ " not found. Run `dbt run` (or full refresh) before diffing."
        ) }}
    {% endif %}

    {# --- Summary: row-level match status --- #}
    {% set summary_query = audit_helper.compare_relations(
        a_relation=before_relation,
        b_relation=current_relation,
        primary_key=pk
    ) %}

    {{ log("=== Diff summary for " ~ mart ~ " (pk: " ~ pk ~ ") ===", info=True) }}
    {{ log("", info=True) }}

    {# compare_relations returns: in_a (bool), in_b (bool), count, percent_of_total
       in_a=True  in_b=True  --> identical rows
       in_a=True  in_b=False --> removed (was in before, not in after)
       in_a=False in_b=True  --> added   (not in before, is in after)
    #}
    {% set summary_results = run_query(summary_query) %}
    {% if summary_results %}
        {{ log("STATUS              | COUNT       | PERCENT", info=True) }}
        {{ log("--------------------|-------------|--------", info=True) }}
        {% for row in summary_results %}
            {% if row[0] == true and row[1] == true %}
                {% set label = 'identical' %}
            {% elif row[0] == true and row[1] == false %}
                {% set label = 'removed (before only)' %}
            {% elif row[0] == false and row[1] == true %}
                {% set label = 'added (after only)' %}
            {% else %}
                {% set label = 'in_a=' ~ row[0] | string ~ ' in_b=' ~ row[1] | string %}
            {% endif %}
            {{ log(
                label ~ " | " ~
                row[2] | string ~ " | " ~
                row[3] | string ~ "%",
                info=True
            ) }}
        {% endfor %}
    {% endif %}

    {{ log("", info=True) }}

    {# --- Column-level diffs for each column --- #}
    {% set columns_query %}
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'analytics'
          AND table_name = '{{ mart }}'
          AND column_name != '{{ pk }}'
        ORDER BY ordinal_position
    {% endset %}

    {% set columns_result = run_query(columns_query) %}
    {% set col_names = columns_result.columns[0].values() %}

    {{ log("=== Column-level diffs ===", info=True) }}
    {{ log("", info=True) }}

    {# compare_column_values returns: column_name, match_status, count_records, percent_of_total #}
    {% for col in col_names %}
        {% set col_query = audit_helper.compare_column_values(
            a_query="SELECT * FROM analytics._before_" ~ mart,
            b_query="SELECT * FROM analytics." ~ mart,
            primary_key=pk,
            column_to_compare=col,
            emojis=false,
            a_relation_name='before',
            b_relation_name='after'
        ) %}

        {% set col_results = run_query(col_query) %}

        {# Only log columns that have non-perfect-match rows #}
        {% set ns = namespace(has_diffs=false) %}
        {% for row in col_results %}
            {% if 'perfect match' not in row[1] | string | lower and 'both are null' not in row[1] | string | lower %}
                {% set ns.has_diffs = true %}
            {% endif %}
        {% endfor %}

        {% if ns.has_diffs %}
            {{ log("  " ~ col ~ ":", info=True) }}
            {% for row in col_results %}
                {{ log("    " ~ row[1] ~ ": " ~ row[2] ~ " (" ~ row[3] ~ "%)", info=True) }}
            {% endfor %}
        {% endif %}
    {% endfor %}

    {{ log("", info=True) }}
    {{ log("Done.", info=True) }}
{% endmacro %}


{% macro cleanup_mart_snapshots() %}
    {% set marts = [
        'mart__invoice_items',
        'mart__invoice_items_map',
        'mart__unmapped_report',
        'mart__price_increases',
        'mart__address_sheet_aggregates',
        'mart__mapping_audit',
        'mart__item_mapping_timeline',
        'mart__item_price_comparison',
    ] %}

    {% for mart in marts %}
        {% set snap_table = '_before_' ~ mart %}
        {% set drop_sql %}
            DROP TABLE IF EXISTS analytics.{{ snap_table }}
        {% endset %}
        {{ log("Dropping analytics." ~ snap_table, info=True) }}
        {% do run_query(drop_sql) %}
    {% endfor %}

    {{ log("All snapshots cleaned up.", info=True) }}
{% endmacro %}
