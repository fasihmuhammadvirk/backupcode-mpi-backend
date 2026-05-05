"""
Visual HTML diff between analytics._before_<mart> and analytics.<mart>.

Produces a color-coded HTML report:
  - Red cells   = value changed
  - Green rows  = added (after only)
  - Grey rows   = removed (before only), with strikethrough
  - White rows  = identical (hidden by default, toggle to show)

Usage:
    uv run scripts/mart_visual_diff.py mart__invoice_items
    uv run scripts/mart_visual_diff.py mart__invoice_items --limit 500
    uv run scripts/mart_visual_diff.py mart__invoice_items --show-identical
    uv run scripts/mart_visual_diff.py --all

Prerequisites:
    dbt run-operation snapshot_marts   (creates _before_ tables)
    dbt run --full-refresh             (refreshes marts)
"""

import argparse
import os
import sys
import webbrowser
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")

OUTPUT_DIR = project_root / "analysis" / "diffs"

MARTS = {
    "mart__invoice_items": "invoice_items_id",
    "mart__invoice_items_map": "id",
    "mart__unmapped_report": "report_id",
    "mart__price_increases": "invoice_items_id",
    "mart__address_sheet_aggregates": "customer_job",
    "mart__mapping_audit": "audit_id",
    "mart__item_mapping_timeline": "id",
    "mart__item_price_comparison": "invoice_items_id",
}


def get_engine():
    host = os.getenv("POSTGRES_HOST")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    db = os.getenv("POSTGRES_DB")
    user = os.getenv("POSTGRES_USERNAME")
    pw = os.getenv("POSTGRES_PASSWORD")
    missing = [name for name, val in {
        "POSTGRES_HOST": host, "POSTGRES_DB": db,
        "POSTGRES_USERNAME": user, "POSTGRES_PASSWORD": pw,
    }.items() if not val]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
    url = URL.create("postgresql", username=user, password=pw, host=host, port=port, database=db)
    return create_engine(url)


def load_table(engine, table: str, schema: str = "analytics") -> pd.DataFrame:
    return pd.read_sql(f'SELECT * FROM {schema}."{table}"', engine)


# Columns that change every refresh (timestamps injected by now()) -- always exclude
AUTO_EXCLUDE = {
    "report_generated_at",
    "audit_generated_at",
    "mart_refreshed_at",
}


def diff_mart(
    mart: str,
    pk: str,
    limit: int | None,
    show_identical: bool,
    exclude_columns: set[str] | None = None,
) -> Path:
    before_table = f"_before_{mart}"
    engine = get_engine()

    print(f"Loading {before_table}...")
    df_before = load_table(engine, before_table)
    print(f"  {len(df_before):,} rows")

    print(f"Loading {mart}...")
    df_after = load_table(engine, mart)
    print(f"  {len(df_after):,} rows")
    engine.dispose()

    # Deduplicate on PK -- keep first occurrence (stable sort)
    df_before = df_before.drop_duplicates(subset=[pk], keep="first")
    df_after = df_after.drop_duplicates(subset=[pk], keep="first")

    df_before = df_before.set_index(pk)
    df_after = df_after.set_index(pk)

    # Exclude noisy columns (timestamps that change every refresh)
    drop_cols = AUTO_EXCLUDE | (exclude_columns or set())
    actual_drops = drop_cols & (set(df_before.columns) | set(df_after.columns))
    if actual_drops:
        print(f"  Excluding columns: {', '.join(sorted(actual_drops))}")
    df_before = df_before.drop(columns=[c for c in drop_cols if c in df_before.columns])
    df_after = df_after.drop(columns=[c for c in drop_cols if c in df_after.columns])

    # Align columns
    all_cols = list(df_before.columns.union(df_after.columns))
    df_before = df_before.reindex(columns=all_cols)
    df_after = df_after.reindex(columns=all_cols)

    # Classify rows
    before_keys = set(df_before.index)
    after_keys = set(df_after.index)

    identical_keys = []
    modified_keys = []
    removed_keys = sorted(before_keys - after_keys, key=str)
    added_keys = sorted(after_keys - before_keys, key=str)

    common_keys = before_keys & after_keys
    for key in sorted(common_keys, key=str):
        row_b = df_before.loc[key]
        row_a = df_after.loc[key]
        if row_b.equals(row_a):
            identical_keys.append(key)
        else:
            modified_keys.append(key)

    summary = {
        "identical": len(identical_keys),
        "modified": len(modified_keys),
        "added": len(added_keys),
        "removed": len(removed_keys),
    }

    print(f"\nSummary:")
    for status, count in summary.items():
        print(f"  {status}: {count:,}")

    # Build HTML
    html_parts = [_html_head(mart, summary, show_identical)]

    # Modified rows (most interesting -- show first)
    if modified_keys:
        display_keys = modified_keys[:limit] if limit else modified_keys
        html_parts.append('<h2>Modified rows</h2>')
        html_parts.append(f'<p>{len(modified_keys):,} total, showing {len(display_keys):,}</p>')
        html_parts.append(_build_modified_table(
            df_before, df_after, display_keys, all_cols, pk
        ))

    # Added rows
    if added_keys:
        display_keys = added_keys[:limit] if limit else added_keys
        html_parts.append('<h2>Added rows (after only)</h2>')
        html_parts.append(f'<p>{len(added_keys):,} total, showing {len(display_keys):,}</p>')
        html_parts.append(_build_simple_table(df_after, display_keys, all_cols, pk, "added"))

    # Removed rows
    if removed_keys:
        display_keys = removed_keys[:limit] if limit else removed_keys
        html_parts.append('<h2>Removed rows (before only)</h2>')
        html_parts.append(f'<p>{len(removed_keys):,} total, showing {len(display_keys):,}</p>')
        html_parts.append(_build_simple_table(df_before, display_keys, all_cols, pk, "removed"))

    # Identical rows (hidden toggle)
    if show_identical and identical_keys:
        display_keys = identical_keys[:limit] if limit else identical_keys
        html_parts.append('<h2>Identical rows</h2>')
        html_parts.append(f'<p>{len(identical_keys):,} total, showing {len(display_keys):,}</p>')
        html_parts.append(_build_simple_table(df_after, display_keys, all_cols, pk, "identical"))

    html_parts.append("</body></html>")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"diff_{mart}_{datetime.now():%Y%m%d_%H%M%S}.html"
    out_path.write_text("\n".join(html_parts))
    print(f"\nReport: {out_path}")
    return out_path


def _html_head(mart: str, summary: dict, show_identical: bool) -> str:
    badge = lambda label, count, color: (
        f'<span class="badge" style="background:{color}">'
        f'{label}: {count:,}</span>'
    )
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Diff: {mart}</title>
<style>
  body {{ font-family: -apple-system, 'Segoe UI', monospace; margin: 20px; background: #fafafa; }}
  h1 {{ color: #333; }}
  h2 {{ color: #555; margin-top: 30px; }}
  .badge {{ display: inline-block; padding: 6px 14px; border-radius: 4px;
            color: white; font-weight: bold; margin-right: 8px; font-size: 14px; }}
  .summary {{ margin: 16px 0; }}
  table {{ border-collapse: collapse; font-size: 12px; width: 100%;
           table-layout: auto; margin-bottom: 20px; }}
  th {{ background: #333; color: white; padding: 6px 10px; text-align: left;
       position: sticky; top: 0; z-index: 1; }}
  td {{ padding: 4px 10px; border-bottom: 1px solid #ddd; white-space: nowrap;
       max-width: 300px; overflow: hidden; text-overflow: ellipsis; }}
  tr:hover td {{ background: #f0f0ff !important; }}
  .cell-changed {{ background: #ffcccc !important; font-weight: bold; }}
  .cell-before {{ color: #999; font-size: 10px; display: block; text-decoration: line-through; }}
  .row-added td {{ background: #ccffcc; }}
  .row-removed td {{ background: #eee; text-decoration: line-through; color: #999; }}
  .row-identical td {{ background: white; }}
  .overflow {{ max-height: 80vh; overflow: auto; border: 1px solid #ccc; }}
  p {{ color: #666; font-size: 13px; }}
</style>
</head><body>
<h1>Diff: {escape(mart)}</h1>
<div class="summary">
  {badge("identical", summary["identical"], "#28a745")}
  {badge("modified", summary["modified"], "#dc3545")}
  {badge("added", summary["added"], "#007bff")}
  {badge("removed", summary["removed"], "#6c757d")}
</div>
"""


def _fmt(val) -> str:
    try:
        if pd.isna(val):
            return '<em>NULL</em>'
    except (ValueError, TypeError):
        pass
    if isinstance(val, float):
        return f"{val:,.4f}" if abs(val) < 1e6 else f"{val:,.2f}"
    return escape(str(val))


def _build_modified_table(
    df_before: pd.DataFrame,
    df_after: pd.DataFrame,
    keys: list,
    cols: list,
    pk: str,
) -> str:
    parts = ['<div class="overflow"><table>']
    parts.append(f"<tr><th>{escape(pk)}</th>")
    for c in cols:
        parts.append(f"<th>{escape(c)}</th>")
    parts.append("</tr>")

    for key in keys:
        row_b = df_before.loc[key]
        row_a = df_after.loc[key]

        parts.append(f"<tr><td><strong>{_fmt(key)}</strong></td>")
        for c in cols:
            val_b = row_b[c]
            val_a = row_a[c]
            try:
                both_na = pd.isna(val_b) and pd.isna(val_a)
            except (ValueError, TypeError):
                both_na = False
            try:
                same = both_na or (str(val_b) == str(val_a))
            except Exception:
                same = False
            if same:
                parts.append(f"<td>{_fmt(val_a)}</td>")
            else:
                parts.append(
                    f'<td class="cell-changed">'
                    f'{_fmt(val_a)}'
                    f'<span class="cell-before">{_fmt(val_b)}</span>'
                    f'</td>'
                )
        parts.append("</tr>")

    parts.append("</table></div>")
    return "\n".join(parts)


def _build_simple_table(
    df: pd.DataFrame,
    keys: list,
    cols: list,
    pk: str,
    row_class: str,
) -> str:
    css = {"added": "row-added", "removed": "row-removed", "identical": "row-identical"}
    cls = css.get(row_class, "")

    parts = ['<div class="overflow"><table>']
    parts.append(f"<tr><th>{escape(pk)}</th>")
    for c in cols:
        parts.append(f"<th>{escape(c)}</th>")
    parts.append("</tr>")

    for key in keys:
        row = df.loc[key]
        parts.append(f'<tr class="{cls}"><td><strong>{_fmt(key)}</strong></td>')
        for c in cols:
            parts.append(f"<td>{_fmt(row[c])}</td>")
        parts.append("</tr>")

    parts.append("</table></div>")
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Visual HTML diff for dbt mart snapshots")
    parser.add_argument("mart", nargs="?", help="Mart name (e.g. mart__invoice_items)")
    parser.add_argument("--all", action="store_true", help="Diff all marts")
    parser.add_argument("--limit", type=int, default=200, help="Max rows per section (default: 200)")
    parser.add_argument("--show-identical", action="store_true", help="Include identical rows")
    parser.add_argument("--exclude", nargs="*", default=[], help="Extra columns to exclude from diff")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open in browser")
    args = parser.parse_args()

    if not args.mart and not args.all:
        parser.error("Provide a mart name or use --all")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be a positive integer")

    extra_exclude = set(args.exclude) if args.exclude else set()
    marts_to_diff = list(MARTS.items()) if args.all else [(args.mart, MARTS.get(args.mart))]

    for mart, pk in marts_to_diff:
        if not pk:
            print(f"Unknown mart: {mart}. Options: {', '.join(MARTS.keys())}")
            sys.exit(1)
        out_path = diff_mart(mart, pk, args.limit, args.show_identical, extra_exclude)
        if not args.no_open:
            webbrowser.open(f"file://{out_path}")


if __name__ == "__main__":
    main()
