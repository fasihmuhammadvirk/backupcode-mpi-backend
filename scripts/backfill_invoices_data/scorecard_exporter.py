"""
Scorecard Export Module

Generates visual comparison reports for prompt optimization results,
similar to the scorecard notebook but for prompt comparison data.
"""

import json
import base64
from io import BytesIO
from pathlib import Path
from typing import Optional
import pandas as pd

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False

# Underscore-prefixed fields to include in HTML JSON display for diagnostics
_DIAGNOSTIC_FIELDS = {
    '_validation_failed_checks',
    '_financial_details',
    '_line_items_details',
    '_header_details',
}

def render_pdf_page(pdf_path: Path, page_num: int = 0, width: int = 400) -> Optional[str]:
    """Render a PDF page as base64 image for HTML display"""
    if not PDF2IMAGE_AVAILABLE:
        return None

    try:
        pages = convert_from_path(str(pdf_path), first_page=page_num+1, last_page=page_num+1, size=(width, None))
        if pages:
            img = pages[0]
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            img_base64 = base64.b64encode(buffer.getvalue()).decode()
            return f"data:image/png;base64,{img_base64}"
    except Exception as e:
        print(f"Error rendering PDF {pdf_path}: {e}")

    return None

def generate_prompt_comparison_html(results_df: pd.DataFrame, show_prompts: bool = True, prompts: Optional[list] = None) -> str:
    """Generate HTML report comparing prompt variations"""

    # Fix data types to ensure numeric columns are properly converted
    results_df = results_df.copy()

    # Ensure string columns are properly typed first
    string_columns = ['prompt_name', 'file_name', 'supplier_variation', 'extracted_vendor', 'error_message', 'extracted_doc_type', 'expected_doc_type', 'doc_type_source']
    for col in string_columns:
        if col in results_df.columns:
            results_df[col] = results_df[col].astype(str)

    # Convert numeric columns to proper types with explicit error handling
    numeric_columns = ['confidence_score', 'extraction_time', 'num_line_items', 'doc_type_page_accuracy']
    for col in numeric_columns:
        if col in results_df.columns:
            # Handle potential string concatenation issues
            results_df[col] = results_df[col].astype(str).str.split().str[0]  # Take first value if concatenated
            results_df[col] = pd.to_numeric(results_df[col], errors='coerce')

    # Convert boolean columns
    boolean_columns = ['extraction_success', 'overall_valid', 'header_valid', 'line_items_valid', 'doc_type_valid']
    for col in boolean_columns:
        if col in results_df.columns:
            results_df[col] = results_df[col].astype(bool)

    # Start HTML document
    html_parts = []
    html_parts.append("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Prompt Optimization Comparison Report</title>
        <style>
            @page { size: A4 landscape; margin: 1cm; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                font-size: 12px;
                line-height: 1.4;
                color: #333;
                margin: 0;
                padding: 20px;
            }
            .summary { background: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
            .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }
            .metric-card { background: white; border: 1px solid #ddd; border-radius: 5px; padding: 15px; }
            .metric-title { font-weight: bold; color: #495057; margin-bottom: 10px; }
            .metric-value { font-size: 24px; font-weight: bold; }
            .metric-success { color: #28a745; }
            .metric-warning { color: #ffc107; }
            .metric-danger { color: #dc3545; }
            .prompt-section { margin-bottom: 40px; border: 1px solid #ddd; border-radius: 5px; overflow: hidden; }
            .prompt-header { background: #f8f9fa; padding: 15px; border-bottom: 1px solid #ddd; }
            .prompt-results { padding: 15px; }
            .result-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; }
            .result-item { border: 1px solid #ddd; border-radius: 5px; overflow: hidden; cursor: pointer; transition: box-shadow 0.15s; }
            .result-item:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.15); }
            .result-item-pass { border-color: #28a745; }
            .result-item-fail { border-color: #dc3545; }
            .result-header { padding: 10px 15px; color: white; font-weight: bold; }
            .result-header-pass { background: #28a745; }
            .result-header-fail { background: #dc3545; }
            .result-body { padding: 15px; }
            .pdf-preview { max-width: 100%; }
            .json-content {
                background: #1e1e1e; color: #d4d4d4; padding: 10px; border-radius: 3px;
                font-family: monospace; font-size: 10px; overflow: auto; max-height: 200px;
                white-space: pre-wrap;
            }
        </style>
    </head>
    <body>
    <h1>Prompt Optimization Comparison Report</h1>
    """)

    # Overall summary
    total_tests = len(results_df)
    total_passed = results_df['overall_valid'].sum()
    pass_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0

    html_parts.append(f"""
    <div class="summary">
        <h3>Overall Summary</h3>
        <p><strong>Total Tests:</strong> {total_tests} |
           <strong>Passed:</strong> {total_passed} |
           <strong>Failed:</strong> {total_tests - total_passed} |
           <strong>Pass Rate:</strong> {pass_rate:.1f}%</p>
    </div>
    """)

    # Calculate summary metrics for extraction performance (all documents)
    prompt_metrics = results_df.groupby('prompt_name').agg({
        'extraction_success': ['count', 'sum', 'mean'],
        'overall_valid': ['sum', 'mean'],
        'header_valid': ['sum', 'mean'],
        'line_items_valid': ['sum', 'mean'],
        'confidence_score': 'mean',
        'extraction_time': 'mean'
    }).round(3)

    # Metrics by prompt
    html_parts.append("""
    <h2>Extraction Performance by Prompt Variation</h2>
    <div class="metric-grid">
    """)

    for prompt_name in prompt_metrics.index:
        total = int(prompt_metrics.loc[prompt_name, ('extraction_success', 'count')])
        success = int(prompt_metrics.loc[prompt_name, ('extraction_success', 'sum')])
        overall_valid = int(prompt_metrics.loc[prompt_name, ('overall_valid', 'sum')])
        overall_rate = prompt_metrics.loc[prompt_name, ('overall_valid', 'mean')] * 100
        avg_time = prompt_metrics.loc[prompt_name, ('extraction_time', 'mean')]

        # Color code based on performance
        if overall_rate >= 90:
            color_class = "metric-success"
        elif overall_rate >= 70:
            color_class = "metric-warning"
        else:
            color_class = "metric-danger"

        html_parts.append(f"""
        <div class="metric-card">
            <div class="metric-title">{prompt_name.replace('_', ' ').title()}</div>
            <div class="metric-value {color_class}">{overall_rate:.1f}%</div>
            <p><strong>Valid:</strong> {overall_valid}/{total}<br>
               <strong>Avg Time:</strong> {avg_time:.2f}s</p>
        </div>
        """)

    html_parts.append("</div>")

    # Classification performance -- all documents
    html_parts.append("""
    <h2>Classification Performance by Prompt Variation (All Documents)</h2>
    <div class="metric-grid">
    """)

    if 'doc_type_valid' in results_df.columns:
        has_doc_type_all = results_df[results_df['expected_doc_type'].astype(str).str.strip().ne('')]
        if not has_doc_type_all.empty:
            cls_metrics = has_doc_type_all.groupby('prompt_name').agg({
                'doc_type_valid': ['count', 'sum', 'mean'],
                'extraction_time': 'mean'
            }).round(3)

            for prompt_name in cls_metrics.index:
                total = int(cls_metrics.loc[prompt_name, ('doc_type_valid', 'count')])
                matched = int(cls_metrics.loc[prompt_name, ('doc_type_valid', 'sum')])
                match_rate = cls_metrics.loc[prompt_name, ('doc_type_valid', 'mean')] * 100
                avg_time = cls_metrics.loc[prompt_name, ('extraction_time', 'mean')]

                if match_rate >= 90:
                    color_class = "metric-success"
                elif match_rate >= 70:
                    color_class = "metric-warning"
                else:
                    color_class = "metric-danger"

                html_parts.append(f"""
                <div class="metric-card">
                    <div class="metric-title">{prompt_name.replace('_', ' ').title()}</div>
                    <div class="metric-value {color_class}">{match_rate:.1f}%</div>
                    <p><strong>Matched:</strong> {matched}/{total}<br>
                       <strong>Avg Time:</strong> {avg_time:.2f}s</p>
                </div>
                """)

    html_parts.append("</div>")

    # Multi-invoice summary (if any detected)
    if 'num_invoices_found' in results_df.columns:
        results_df['num_invoices_found'] = pd.to_numeric(results_df['num_invoices_found'], errors='coerce').fillna(1)
        multi_rows = results_df[results_df['num_invoices_found'] > 1]
        if not multi_rows.empty:
            html_parts.append("""
            <h2>Multi-Invoice Detections</h2>
            <table style="width:100%; border-collapse:collapse; margin-bottom:30px;">
            <tr style="background:#f8f9fa;">
                <th style="padding:8px; border:1px solid #ddd; text-align:left;">Prompt</th>
                <th style="padding:8px; border:1px solid #ddd; text-align:left;">File</th>
                <th style="padding:8px; border:1px solid #ddd; text-align:left;">Vendor</th>
                <th style="padding:8px; border:1px solid #ddd; text-align:center;">Invoices</th>
                <th style="padding:8px; border:1px solid #ddd; text-align:left;">Ref Nos</th>
                <th style="padding:8px; border:1px solid #ddd; text-align:center;">Valid</th>
            </tr>
            """)
            for _, mrow in multi_rows.iterrows():
                valid_icon = "[PASS]" if mrow.get('overall_valid', False) else "[FAIL]"
                valid_color = "#28a745" if mrow.get('overall_valid', False) else "#dc3545"
                html_parts.append(f"""
                <tr>
                    <td style="padding:8px; border:1px solid #ddd;">{mrow['prompt_name']}</td>
                    <td style="padding:8px; border:1px solid #ddd;">{mrow['file_name']}</td>
                    <td style="padding:8px; border:1px solid #ddd;">{mrow.get('supplier_variation', '')}</td>
                    <td style="padding:8px; border:1px solid #ddd; text-align:center; font-weight:bold;">{int(mrow['num_invoices_found'])}</td>
                    <td style="padding:8px; border:1px solid #ddd;">{mrow.get('all_ref_nos', '')}</td>
                    <td style="padding:8px; border:1px solid #ddd; text-align:center; color:{valid_color}; font-weight:bold;">{valid_icon}</td>
                </tr>
                """)
            html_parts.append("</table>")

    # Doc_type classification accuracy section
    if 'extracted_doc_type' in results_df.columns and 'expected_doc_type' in results_df.columns:
        has_doc_type = results_df[results_df['expected_doc_type'].astype(str).str.strip().ne('')]
        if not has_doc_type.empty:
            html_parts.append("""
            <h2>Document Type Classification (Gemini vs Expected)</h2>
            <table style="width:100%; border-collapse:collapse; margin-bottom:30px;">
            <tr style="background:#f8f9fa;">
                <th style="padding:8px; border:1px solid #ddd; text-align:left;">Prompt</th>
                <th style="padding:8px; border:1px solid #ddd; text-align:left;">File</th>
                <th style="padding:8px; border:1px solid #ddd; text-align:left;">Vendor</th>
                <th style="padding:8px; border:1px solid #ddd; text-align:center;">Gemini doc_type</th>
                <th style="padding:8px; border:1px solid #ddd; text-align:center;">Expected doc_type</th>
                <th style="padding:8px; border:1px solid #ddd; text-align:center;">Source</th>
                <th style="padding:8px; border:1px solid #ddd; text-align:center;">Match</th>
                <th style="padding:8px; border:1px solid #ddd; text-align:center;">Page Acc</th>
            </tr>
            """)
            for _, drow in has_doc_type.iterrows():
                gemini_dt = drow.get('extracted_doc_type', '')
                expected_dt = drow.get('expected_doc_type', '')
                source = drow.get('doc_type_source', '')
                source_label = "GT" if source == "ground_truth" else "--"
                source_color = "#6f42c1" if source == "ground_truth" else "#6c757d"
                match = drow.get('doc_type_valid', False)
                match_icon = "[OK]" if match else "[MISMATCH]"
                match_color = "#28a745" if match else "#dc3545"
                page_acc = drow.get('doc_type_page_accuracy', 0.0)
                page_acc_str = f"{page_acc * 100:.0f}%" if page_acc is not None else ""
                html_parts.append(f"""
                <tr>
                    <td style="padding:8px; border:1px solid #ddd;">{drow['prompt_name']}</td>
                    <td style="padding:8px; border:1px solid #ddd;">{drow['file_name']}</td>
                    <td style="padding:8px; border:1px solid #ddd;">{drow.get('supplier_variation', '')}</td>
                    <td style="padding:8px; border:1px solid #ddd; text-align:center; font-weight:bold;">{gemini_dt}</td>
                    <td style="padding:8px; border:1px solid #ddd; text-align:center;">{expected_dt}</td>
                    <td style="padding:8px; border:1px solid #ddd; text-align:center; color:{source_color}; font-weight:bold;">{source_label}</td>
                    <td style="padding:8px; border:1px solid #ddd; text-align:center; color:{match_color}; font-weight:bold;">{match_icon}</td>
                    <td style="padding:8px; border:1px solid #ddd; text-align:center;">{page_acc_str}</td>
                </tr>
                """)
            html_parts.append("</table>")

            # Summary stats
            if 'doc_type_valid' in results_df.columns:
                dt_valid = has_doc_type['doc_type_valid'].astype(bool)
                dt_match_rate = dt_valid.mean() * 100 if len(dt_valid) > 0 else 0
                dt_color = "#28a745" if dt_match_rate >= 90 else "#ffc107" if dt_match_rate >= 70 else "#dc3545"

                # Breakdown by source
                source_breakdown = ""
                if 'doc_type_source' in has_doc_type.columns:
                    for source, label, color in [
                        ('ground_truth', 'Ground Truth', '#6f42c1'),
                    ]:
                        src_rows = has_doc_type[has_doc_type['doc_type_source'] == source]
                        if src_rows.empty:
                            continue
                        src_valid = src_rows['doc_type_valid'].astype(bool)
                        src_rate = src_valid.mean() * 100
                        src_color = "#28a745" if src_rate >= 90 else "#ffc107" if src_rate >= 70 else "#dc3545"
                        source_breakdown += (
                            f' | <strong>{label}:</strong> '
                            f'<span style="color:{src_color}; font-weight:bold;">{src_rate:.1f}%</span> '
                            f'({src_valid.sum()}/{len(src_valid)})'
                        )

                page_acc_html = ""
                if 'doc_type_page_accuracy' in has_doc_type.columns:
                    avg_page_acc = has_doc_type['doc_type_page_accuracy'].mean() * 100
                    if avg_page_acc != dt_match_rate:
                        pa_color = "#28a745" if avg_page_acc >= 90 else "#ffc107" if avg_page_acc >= 70 else "#dc3545"
                        page_acc_html = (
                            f' | <strong>Page Accuracy:</strong> '
                            f'<span style="color:{pa_color}; font-weight:bold;">{avg_page_acc:.1f}%</span>'
                        )

                html_parts.append(f"""
                <div class="summary" style="margin-bottom:30px;">
                    <p><strong>Doc Type Match Rate:</strong>
                    <span style="color:{dt_color}; font-weight:bold;">{dt_match_rate:.1f}%</span>
                    ({dt_valid.sum()}/{len(dt_valid)} matched){source_breakdown}{page_acc_html}</p>
                </div>
                """)

    # Baseline vs Classification Diff section
    prompt_names = results_df['prompt_name'].unique().tolist()
    if 'baseline' in prompt_names and 'classification' in prompt_names:
        pivot = results_df.pivot_table(
            index='file_name',
            columns='prompt_name',
            values='overall_valid',
            aggfunc='first',
        )
        if 'baseline' in pivot.columns and 'classification' in pivot.columns:
            divergent = pivot[pivot['baseline'] != pivot['classification']].dropna()
            if not divergent.empty:
                # Build lookup for vendor and doc_type per prompt x file
                file_info = results_df.set_index(['file_name', 'prompt_name'])

                html_parts.append("""
                <h2>Baseline vs Classification Diff</h2>
                <p style="color:#6c757d; margin-bottom:10px;">Files where baseline and classification disagree on overall_valid.</p>
                <table style="width:100%; border-collapse:collapse; margin-bottom:30px;">
                <tr style="background:#f8f9fa;">
                    <th style="padding:8px; border:1px solid #ddd; text-align:left;">File</th>
                    <th style="padding:8px; border:1px solid #ddd; text-align:left;">Vendor</th>
                    <th style="padding:8px; border:1px solid #ddd; text-align:center;">Baseline</th>
                    <th style="padding:8px; border:1px solid #ddd; text-align:center;">Classification</th>
                    <th style="padding:8px; border:1px solid #ddd; text-align:center;">Baseline doc_type</th>
                    <th style="padding:8px; border:1px solid #ddd; text-align:center;">Classification doc_type</th>
                </tr>
                """)

                for fname in divergent.index:
                    b_valid = divergent.loc[fname, 'baseline']
                    c_valid = divergent.loc[fname, 'classification']
                    b_icon = "[PASS]" if b_valid else "[FAIL]"
                    c_icon = "[PASS]" if c_valid else "[FAIL]"
                    b_color = "#28a745" if b_valid else "#dc3545"
                    c_color = "#28a745" if c_valid else "#dc3545"

                    # Look up vendor and doc_type from each prompt's row
                    vendor = ""
                    b_doc_type = ""
                    c_doc_type = ""
                    if (fname, 'baseline') in file_info.index:
                        b_row = file_info.loc[(fname, 'baseline')]
                        if isinstance(b_row, pd.DataFrame):
                            b_row = b_row.iloc[0]
                        vendor = b_row.get('supplier_variation', '') or b_row.get('extracted_vendor', '')
                        b_doc_type = b_row.get('extracted_doc_type', '')
                    if (fname, 'classification') in file_info.index:
                        c_row = file_info.loc[(fname, 'classification')]
                        if isinstance(c_row, pd.DataFrame):
                            c_row = c_row.iloc[0]
                        c_doc_type = c_row.get('extracted_doc_type', '')
                        if not vendor:
                            vendor = c_row.get('supplier_variation', '') or c_row.get('extracted_vendor', '')

                    html_parts.append(f"""
                    <tr>
                        <td style="padding:8px; border:1px solid #ddd;">{fname}</td>
                        <td style="padding:8px; border:1px solid #ddd;">{vendor}</td>
                        <td style="padding:8px; border:1px solid #ddd; text-align:center; color:{b_color}; font-weight:bold;">{b_icon}</td>
                        <td style="padding:8px; border:1px solid #ddd; text-align:center; color:{c_color}; font-weight:bold;">{c_icon}</td>
                        <td style="padding:8px; border:1px solid #ddd; text-align:center;">{b_doc_type}</td>
                        <td style="padding:8px; border:1px solid #ddd; text-align:center;">{c_doc_type}</td>
                    </tr>
                    """)

                html_parts.append("</table>")

    # Prompts section (if requested)
    if show_prompts and prompts:
        html_parts.append("<h2>Prompt Variations Tested</h2>")

        # Create a lookup for prompts by name
        prompt_lookup = {p.name: p for p in prompts} if prompts else {}

        # Get unique prompts from the data
        unique_prompts = results_df.groupby('prompt_name')['prompt_hash'].first()

        for prompt_name in unique_prompts.index:
            prompt_hash = unique_prompts[prompt_name]
            prompt_obj = prompt_lookup.get(prompt_name)

            # Display system prompt
            system_content = ""
            if prompt_obj and hasattr(prompt_obj, 'system_prompt'):
                system_content = prompt_obj.system_prompt[:1000] + ("..." if len(prompt_obj.system_prompt) > 1000 else "")
            else:
                system_content = "System prompt not available"

            # Display user prompt template
            user_content = ""
            if prompt_obj and hasattr(prompt_obj, 'user_prompt'):
                user_content = prompt_obj.user_prompt[:1000] + ("..." if len(prompt_obj.user_prompt) > 1000 else "")
            else:
                user_content = "User prompt not available"

            # Display description
            description = ""
            if prompt_obj and hasattr(prompt_obj, 'description'):
                description = prompt_obj.description
            else:
                description = "No description available"

            html_parts.append(f"""
            <div class="prompt-section" style="margin-bottom: 30px; border: 1px solid #ddd; border-radius: 5px;">
                <div class="prompt-header" style="background: #f8f9fa; padding: 15px; border-bottom: 1px solid #ddd;">
                    <h3>{prompt_name.replace('_', ' ').title()}</h3>
                    <p><strong>Hash:</strong> {prompt_hash}</p>
                    <p><strong>Description:</strong> {description}</p>
                </div>
                <div class="prompt-content" style="padding: 15px;">
                    <h4>System Prompt</h4>
                    <pre style="background: #f8f8f8; padding: 10px; border-radius: 3px; font-size: 11px; overflow-x: auto; white-space: pre-wrap;">{system_content}</pre>

                    <h4 style="margin-top: 20px;">User Prompt Template</h4>
                    <pre style="background: #f8f8f8; padding: 10px; border-radius: 3px; font-size: 11px; overflow-x: auto; white-space: pre-wrap;">{user_content}</pre>
                </div>
            </div>
            """)

        html_parts.append("<hr>")
    elif show_prompts:
        html_parts.append("<h2>Prompt Variations Tested</h2>")
        html_parts.append('<p><em>Pass prompt objects to the prompts parameter to display full prompt content.</em></p>')
        html_parts.append("<hr>")

    # Detailed results by prompt
    html_parts.append("<h2>Detailed Results by Prompt</h2>")

    for prompt_name in results_df['prompt_name'].unique():
        prompt_results = results_df[results_df['prompt_name'] == prompt_name]

        html_parts.append(f"""
        <div class="prompt-section">
            <div class="prompt-header">
                <h3>{prompt_name.replace('_', ' ').title()}</h3>
                <p>Tests: {len(prompt_results)} |
                   Passed: {prompt_results['overall_valid'].sum()} |
                   Pass Rate: {prompt_results['overall_valid'].mean()*100:.1f}%</p>
            </div>
            <div class="prompt-results">
                <div class="result-grid">
        """)

        # Show all results
        sample_results = prompt_results

        for idx, row in sample_results.iterrows():
            status = "pass" if row['overall_valid'] else "fail"
            status_text = "[PASS]" if row['overall_valid'] else "[FAIL]"

            # Try to find PDF file for preview
            pdf_preview = ""
            pdf_path = None
            if 'file_path' in row and row['file_path']:
                candidate = Path(row['file_path'])
                if candidate.exists():
                    pdf_path = candidate
            if pdf_path is None and 'file_name' in row and row['file_name']:
                pdf_path = next(
                    (p for p in [Path(f"temp_pdfs/{row['file_name']}")] if p.exists()),
                    None
                )

            if pdf_path:
                file_url = pdf_path.resolve().as_uri()
                open_link = f'<div style="text-align:center; margin-top:4px;"><a href="{file_url}" target="_blank" style="font-size:11px;">Open PDF</a></div>'
                img_data = render_pdf_page(pdf_path)
                if img_data:
                    pdf_preview = (
                        f'<a href="{file_url}" target="_blank" title="Open PDF">'
                        f'<img src="{img_data}" class="pdf-preview"></a>'
                        f'{open_link}'
                    )
                else:
                    pdf_preview = f'<div style="background: #f8f8f8; padding: 20px; text-align: center;">PDF: {row.get("file_name", pdf_path.name)}<br><small>(Install pdf2image to preview)</small></div>{open_link}'
            elif 'file_name' in row and row['file_name']:
                pdf_preview = f'<div style="background: #f8f8f8; padding: 20px; text-align: center;">PDF: {row["file_name"]}<br><small>(File not found)</small></div>'

            # Format extracted data (if available in raw_extraction column)
            extracted_data = ""
            if 'raw_extraction' in row and row['raw_extraction']:
                try:
                    if isinstance(row['raw_extraction'], str):
                        data = json.loads(row['raw_extraction'])
                    else:
                        data = row['raw_extraction']

                    # Multi-invoice: render each invoice separately with a header
                    if isinstance(data, dict) and 'invoices' in data and isinstance(data['invoices'], list):
                        inv_list = data['invoices']
                        if len(inv_list) > 1:
                            parts = []
                            for inv_idx, inv in enumerate(inv_list, 1):
                                ref = inv.get('ref_no', '?')
                                parts.append(f"--- Invoice {inv_idx} (ref_no: {ref}) ---")
                                display_inv = {k: v for k, v in inv.items() if not k.startswith('_') or k in _DIAGNOSTIC_FIELDS}
                                parts.append(json.dumps(display_inv, indent=2, default=str))
                            extracted_data = "\n\n".join(parts)
                        elif len(inv_list) == 1:
                            # Single invoice in multi wrapper -- unwrap for cleaner display
                            display_inv = {k: v for k, v in inv_list[0].items() if not k.startswith('_') or k in _DIAGNOSTIC_FIELDS}
                            extracted_data = json.dumps(display_inv, indent=2, default=str)
                        else:
                            extracted_data = json.dumps(data, indent=2, default=str)
                    elif isinstance(data, dict):
                        display_data = {k: v for k, v in data.items() if not k.startswith('_') or k in _DIAGNOSTIC_FIELDS}
                        extracted_data = json.dumps(display_data, indent=2, default=str)
                    else:
                        extracted_data = json.dumps(data, indent=2, default=str)
                except Exception:
                    extracted_data = str(row['raw_extraction'])
            else:
                # Show basic extracted fields
                extracted_data = json.dumps({
                    'vendor': row.get('extracted_vendor', ''),
                    'buyer': row.get('extracted_buyer', ''),
                    'doc_type': row.get('extracted_doc_type', ''),
                    'confidence_score': row.get('confidence_score', 0),
                    'num_line_items': row.get('num_line_items', 0),
                    'header_valid': row.get('header_valid', False),
                    'line_items_valid': row.get('line_items_valid', False),
                    'missing_header_fields': row.get('missing_header_fields', ''),
                    'missing_line_item_fields': row.get('missing_line_item_fields', ''),
                    'error_message': row.get('error_message', '')
                }, indent=2)

            # Multi-invoice badge
            num_inv = int(row.get('num_invoices_found', 1) or 1)
            multi_badge = ""
            if num_inv > 1:
                all_refs = row.get('all_ref_nos', '') or ''
                multi_badge = (
                    f' | <span style="background:#17a2b8;color:#fff;padding:2px 8px;border-radius:3px;">'
                    f'{num_inv} invoices</span> ref_nos: {all_refs}'
                )

            html_parts.append(f"""
            <div class="result-item result-item-{status}">
                <div class="result-header result-header-{status}">
                    {status_text} | {row['file_name']} | {row.get('supplier_variation', 'Unknown')}{multi_badge}
                </div>
                <div class="result-body">
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                        <div>
                            <h4>PDF Preview</h4>
                            {pdf_preview}
                        </div>
                        <div>
                            <h4>Extracted Data</h4>
                            <pre class="json-content">{extracted_data}</pre>
                        </div>
                    </div>
                </div>
            </div>
            """)

        html_parts.append("</div></div></div>")

    # Modal overlay and script
    html_parts.append("""
    <div id="result-modal" style="
        display:none; position:fixed; inset:0; z-index:9999;
        background:rgba(0,0,0,0.6); overflow-y:auto; padding:30px;
    ">
        <div id="modal-inner" style="
            background:#fff; max-width:1200px; margin:0 auto; border-radius:8px;
            overflow:hidden; position:relative;
        ">
            <button id="modal-close" style="
                position:sticky; top:0; float:right; z-index:1;
                margin:10px; padding:6px 14px; font-size:18px;
                background:#f8f9fa; border:1px solid #ccc; border-radius:4px; cursor:pointer;
            ">X</button>
            <div id="modal-content" style="padding:20px; clear:both;"></div>
        </div>
    </div>

    <script>
    (function() {
        var modal = document.getElementById('result-modal');
        var inner = document.getElementById('modal-inner');
        var content = document.getElementById('modal-content');

        // Click any result-item to open modal
        document.addEventListener('click', function(e) {
            var item = e.target.closest('.result-item');
            if (!item) return;

            // Clone the result into the modal at full width
            var clone = item.cloneNode(true);
            clone.style.cursor = 'default';
            clone.style.border = 'none';

            // Expand the grid to side-by-side at full width
            var grid = clone.querySelector('[style*="grid-template-columns"]');
            if (grid) {
                grid.style.gridTemplateColumns = '1fr 1fr';
            }

            // Make the PDF preview fill its column
            var imgs = clone.querySelectorAll('.pdf-preview');
            for (var i = 0; i < imgs.length; i++) {
                imgs[i].style.maxWidth = '100%';
                imgs[i].style.width = '100%';
            }

            // Expand the JSON block
            var pres = clone.querySelectorAll('.json-content');
            for (var j = 0; j < pres.length; j++) {
                pres[j].style.maxHeight = 'none';
                pres[j].style.fontSize = '12px';
            }

            content.innerHTML = '';
            content.appendChild(clone);
            modal.style.display = 'block';
            document.body.style.overflow = 'hidden';
        });

        // Close on X button
        document.getElementById('modal-close').addEventListener('click', function() {
            modal.style.display = 'none';
            document.body.style.overflow = '';
        });

        // Close on backdrop click (but not on inner content)
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                modal.style.display = 'none';
                document.body.style.overflow = '';
            }
        });

        // Close on Escape key
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && modal.style.display === 'block') {
                modal.style.display = 'none';
                document.body.style.overflow = '';
            }
        });
    })();
    </script>
    """)

    html_parts.append("</body></html>")
    return "".join(html_parts)

def create_prompt_comparison_report(results_df: pd.DataFrame, output_path: Path, format: str = 'html',
                                   show_prompts: bool = True, prompts: Optional[list] = None):
    """Create visual comparison report in specified format"""

    try:
        if format == 'html':
            html_content = generate_prompt_comparison_html(results_df, show_prompts, prompts)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

        elif format == 'pdf':
            try:
                from weasyprint import HTML as WeasyHTML
                html_content = generate_prompt_comparison_html(results_df, show_prompts, prompts)
                WeasyHTML(string=html_content).write_pdf(output_path)
            except ImportError:
                raise ImportError("weasyprint not available for PDF generation. Install with: uv add weasyprint")

        else:
            raise ValueError(f"Unsupported format: {format}. Use 'html' or 'pdf'.")

    except Exception as e:
        print(f"Error generating {format.upper()} report: {e}")
        print("DataFrame info:")
        print(f"  Shape: {results_df.shape}")
        print(f"  Columns: {list(results_df.columns)}")
        print(f"  Data types: {results_df.dtypes}")
        if len(results_df) > 0:
            print("  Sample data:")
            print(results_df.head(2))
        raise
