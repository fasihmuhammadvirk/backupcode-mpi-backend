#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCS_DIR="$SCRIPT_DIR/dbt_docs"
TARGET_DIR="$SCRIPT_DIR/target"

cd "$SCRIPT_DIR"

echo "Generating dbt docs..."
uv run python run_dbt.py docs generate

for file in index.html manifest.json catalog.json; do
    if [ ! -f "$TARGET_DIR/$file" ]; then
        echo "ERROR: $TARGET_DIR/$file not found. dbt docs generate may have failed."
        exit 1
    fi
done

cp "$TARGET_DIR/index.html"    "$DOCS_DIR/index.html"
cp "$TARGET_DIR/manifest.json" "$DOCS_DIR/manifest.json"
cp "$TARGET_DIR/catalog.json"  "$DOCS_DIR/catalog.json"

echo "dbt docs copied to $DOCS_DIR"
echo "Remember to commit the updated files in mpi_analytics/dbt_docs/"
