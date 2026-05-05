#!/usr/bin/env python3
"""
Invoice Prompt Optimization Framework

This module provides a systematic approach to optimize extraction prompts using
parallel processing and the existing validation infrastructure. It enables rapid
testing of different prompt variations across supplier types to achieve 99% accuracy.

Usage:
    # Test baseline prompts on 100 PDFs
    python scripts/backfill_invoices_data/prompt_optimizer.py

    # Quick test with fewer samples
    python scripts/backfill_invoices_data/prompt_optimizer.py --samples-per-supplier 5

    # Test specific prompts in parallel
    python scripts/backfill_invoices_data/prompt_optimizer.py --parallel --workers 4
"""

import argparse
import json
import time
import hashlib
import subprocess
import signal
import sys
import logging
import tempfile
import shutil
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from google.genai import types

from db_utils import get_recent_pdfs_by_vendor, get_pdfs_by_ref_nos, get_pdfs_by_s3_keys
from s3 import download_file_from_s3, local_dir
from scorecard_exporter import create_prompt_comparison_report
from data_extraction import gemini_client, validate_and_enrich
from enums import GEMINI_MODEL
from pdf_utils import normalize_pdf_text, extract_text_from_pdf
from prompt_schemas import build_gemini_invoice_schema, build_gemini_multi_invoice_schema
from mpi_backend.utils.document_types import DocumentType


logger = logging.getLogger(__name__)

# Get the repository root directory
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _build_classification_schema() -> dict:
    """Build schema with improved doc_type enum and descriptions from DocumentType.

    Used by the 'classification' prompt variation to A/B test the new
    doc_type schema against the v16 baseline in prompt_schemas.py.
    """
    import copy
    schema = copy.deepcopy(build_gemini_multi_invoice_schema())
    schema['properties']['invoices']['items']['properties']['doc_type'] = {
        "type": "string",
        "description": DocumentType.gemini_description(),
        "enum": DocumentType.gemini_enum(),
    }

    schema['properties']['invoices']['items']['required'] += ["doc_type"]
    return schema

# Invoices (by ref_no) that MUST always be included in the test set
# Replace these with invoices that you are improving/iterating on
REQUIRED_REF_NOS = [
    "590140",
    "504002A",
    "594426",
    "149624",
    "152515",
    "167798",
    "172050",
    "172532",
    "173743",
    "175126",
]

# PDFs (by S3 key) that MUST always be included in the test set.
# These are known multi-invoice PDFs for the multi-invoice experiment.
REQUIRED_S3_KEYS = [
    "invoices/info_at_wwps.co/2025-03/195eeb83293ab679_PH_17_033125_73200221.PDF",
    # These are "BID PROPOSAL", during classification of doc_type Gemini returned it as "SALE ORDER" which
    # caused it to be filtered out
    "invoices/bill.krueger_at_brucesupply.net/2023-06/18876cce3c26e85c_5810453_Bid-OER1072_075604_001_QPRINT_1.pdf",
    "invoices/jonathan.c_at_gothampipesupply.com/2023-01/1857e9c4f3826dd0_5784872_Bid-OER1072_151721_800_QPRINT_1.pdf",
    "invoices/jonathan.c_at_gothampipesupply.com/2022-09/183149eda43d5f5b_5759389_Bid-OER1072_165507_800_QPRINT_1.pdf",
    "invoices/jonathan.c_at_gothampipesupply.com/2022-09/183149eda43d5f5b_5759394_Bid-OER1072_170030_800_QPRINT_1.pdf",
    "invoices/douglas.ynacay_at_brucesupply.net/2023-01/185a291739556630_5786512_Bid-OER1072_152404_004_QPRINT_1.pdf",
    "invoices/jonathan.c_at_gothampipesupply.com/2023-04/1874d5116e7d1f38_5804443_Bid-OER1072_130843_800_QPRINT_1.pdf",
    "invoices/vincent.errico_at_brucesupply.net/2022-03/17f561500a075d88_5716893_Bid-OER1072_124916_001_QPRINT_1.pdf",
    "invoices/jonathan.c_at_gothampipesupply.com/2022-09/1831866825508a57_5759386_Bid-OER1072_103432_800_QPRINT_1.pdf",
    "invoices/vincent.errico_at_brucesupply.net/2022-01/17e9d10bd20040e5_5708013_Bid-OER1072_141955_001_QPRINT_1.pdf",
    "invoices/robert.k_at_gothampipesupply.com/2023-07/1894bd591ea354af_5825023_Bid-OER1072_163452_800_QPRINT_1.pdf",
    "invoices/vincent.errico_at_brucesupply.net/2022-02/17ed5414e7cbde8a_5710216_Bid-OER1072_122349_001_QPRINT_1.pdf",
    "invoices/vincent.errico_at_brucesupply.net/2022-01/17e9d10bd20040e5_5708015_Bid-OER1072_141927_001_QPRINT_1.pdf",
    "invoices/jonathan.c_at_gothampipesupply.com/2023-01/1857e9c4f3826dd0_5784899_Bid-OER1072_160513_800_QPRINT_1.pdf",
    "invoices/robert.k_at_gothampipesupply.com/2023-07/1894bd591ea354af_5825025_Bid-OER1072_164015_800_QPRINT_1.pdf",

    # Has statement then invoices with last one being credit (but called invoice)
    "invoices/statements_at_theplumbingexchange.com/2021-03/1786c9a949a014e4_AR-ST-mpip01-Mar2021.pdf",

]

@dataclass
class PromptVariation:
    """Container for a prompt variation to test"""
    name: str
    system_prompt: str
    user_prompt: str
    description: str
    schema_type: str = "single"  # "single" or "multi"

    def get_hash(self) -> str:
        """Get a hash of the prompt content for identification"""
        content = self.system_prompt + self.user_prompt
        return hashlib.md5(content.encode()).hexdigest()[:8]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'PromptVariation':
        """Create from dictionary"""
        return cls(**data)

@dataclass
class ExtractionResult:
    """Container for extraction results with detailed metrics"""
    file_name: str
    supplier_variation: str
    prompt_name: str
    prompt_hash: str
    extraction_success: bool
    header_valid: bool
    line_items_valid: bool
    financial_valid: bool
    overall_valid: bool
    confidence_score: float
    num_line_items: int
    extracted_vendor: str
    extracted_misc_charges_count: int
    missing_header_fields: List[str]
    missing_line_item_fields: List[str]
    extraction_time: float
    error_message: str
    num_invoices_found: int = 1
    all_ref_nos: str = ""  # semicolon-separated ref_nos from all invoices
    extracted_ref_no: str = ""  # semicolon-separated ref_nos (populated for multi-invoice)

class PromptOptimizer:
    """Main class for optimizing extraction prompts"""

    def __init__(self, output_dir: str | Path | None = None):
        if output_dir is None:
            # Default to output/ in project root
            output_dir = REPO_ROOT / "output" / "prompt_optimizer"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="prompt_exp_"))

        # Load ground truth for doc_type comparison (if available)
        gt_path = REPO_ROOT / "analysis" / "pdf_classification_ground_truth.json"
        self._doc_type_ground_truth: dict[str, list[str]] = (
            json.loads(gt_path.read_text()) if gt_path.exists() else {}
        )
        if self._doc_type_ground_truth:
            print(f"Loaded {len(self._doc_type_ground_truth)} ground truth doc_type annotations")

    def __del__(self):
        """Cleanup temporary directory"""
        if hasattr(self, 'temp_dir') and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def create_baseline_prompts(self) -> List[PromptVariation]:
        """Create baseline prompt variations to test"""
        # Import here to avoid circular imports in worker processes
        from data_extraction import GEMINI_SYSTEM_PROMPT, GEMINI_USER_PROMPT_TEMPLATE

        prompts = []

        # Current prompt (baseline)
        prompts.append(PromptVariation(
            name="baseline",
            system_prompt=GEMINI_SYSTEM_PROMPT,
            user_prompt=GEMINI_USER_PROMPT_TEMPLATE,
            description="Current production prompt",
            schema_type="multi",
        ))
        
        classification_prompt_system = GEMINI_SYSTEM_PROMPT + """
## PER-DOCUMENT TYPE CLASSIFICATION
For EACH entry in the "invoices" array, you MUST accurately classify its doc_type.
CRITICAL: A single PDF may contain DIFFERENT document types across pages.
Page 1 might be a STATEMENT while pages 2+ are INVOICES. Classify each independently.
Do NOT let the first page's document type influence your classification of subsequent pages.

## DISAMBIGUATION RULES FOR COMMONLY CONFUSED TYPES
- Documents titled "BID PROPOSAL", "QUOTE", "ESTIMATE", or "PROPOSAL" are BID, not SALE_ORDER.
- SALE_ORDER requires an explicit sales order number or order confirmation. A bid/quote is NOT a sales order.
- STATEMENT summarizes multiple invoices or account activity. A single invoice is INVOICE, not STATEMENT.
        """

        prompts.append(PromptVariation(
            name="classification",
            system_prompt=classification_prompt_system,
            user_prompt=GEMINI_USER_PROMPT_TEMPLATE,
            description="classification prompt",
            schema_type="classification",
        ))

        return prompts

    def sample_test_pdfs(self, pdf_dir: str, samples_per_supplier: int = 12) -> List[Dict[str, Any]]:
        """Sample PDFs strategically across supplier variations.

        Supports both flat directories (PDFs named <supplier>_*.pdf) and
        nested directories (vendor_name/<file>.pdf) like analysis/low_validation_invoices/.
        """
        pdf_path = Path(pdf_dir)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF directory not found: {pdf_path}")

        # Group PDFs by supplier -- support both flat and nested layouts
        supplier_groups: Dict[str, List[Path]] = {}
        for pdf_file in pdf_path.rglob("*.[pP][dD][fF]"):
            # Nested layout: parent dir name is the supplier
            if pdf_file.parent != pdf_path:
                supplier = pdf_file.parent.name
            else:
                # Flat layout: first token of filename
                supplier = pdf_file.name.split('_')[0]
            supplier_groups.setdefault(supplier, []).append(pdf_file)

        # Sample from each supplier
        sampled_pdfs = []
        for supplier, pdfs in supplier_groups.items():
            # Take up to samples_per_supplier PDFs from each supplier
            sample_count = min(samples_per_supplier, len(pdfs))
            sampled = pdfs[:sample_count]

            for pdf_file in sampled:
                sampled_pdfs.append({
                    'file_path': str(pdf_file),
                    'file_name': pdf_file.name,
                    'supplier_variation': supplier
                })

        print(f"Sampled {len(sampled_pdfs)} PDFs from {len(supplier_groups)} suppliers")
        for supplier, count in [(s, len([p for p in sampled_pdfs if p['supplier_variation'] == s]))
                               for s in supplier_groups.keys()]:
            print(f"  {supplier}: {count} PDFs")

        return sampled_pdfs

    def sample_test_pdfs_from_db(self, samples_per_supplier: int = 12) -> List[Dict[str, Any]]:
        """Sample PDFs by querying DB for recent invoices and downloading from S3.

        Queries email_vendor_mapping for active vendors, gets the most recent
        PDFs per vendor from pdf_extraction_queue, and downloads them from S3.
        Also always includes invoices listed in REQUIRED_REF_NOS.
        Skips files that already exist locally. Skips download failures gracefully.

        Returns same format as sample_test_pdfs():
            [{file_path, file_name, supplier_variation}]
        """

        rows = get_recent_pdfs_by_vendor(samples_per_supplier)
        if not rows:
            raise RuntimeError("No PDFs found in DB. Check email_vendor_mapping and pdf_extraction_queue.")

        # Merge required ref_no PDFs (deduplicate by s3_key)
        existing_keys = {row['s3_key'] for row in rows}
        required_rows = get_pdfs_by_ref_nos(REQUIRED_REF_NOS)
        added = 0
        for req in required_rows:
            if req['s3_key'] not in existing_keys:
                rows.append(req)
                existing_keys.add(req['s3_key'])
                added += 1
        if required_rows:
            print(f"Required ref_nos: {len(required_rows)} found, {added} added (rest already sampled)")
        else:
            print(f"WARNING: No PDFs found for required ref_nos: {REQUIRED_REF_NOS}")

        # Merge required S3 key PDFs (e.g., known multi-invoice files)
        s3_key_rows = get_pdfs_by_s3_keys(REQUIRED_S3_KEYS)
        s3_added = 0
        for req in s3_key_rows:
            if req['s3_key'] not in existing_keys:
                rows.append(req)
                existing_keys.add(req['s3_key'])
                s3_added += 1
        if s3_key_rows:
            print(f"Required s3_keys: {len(s3_key_rows)} found, {s3_added} added (rest already sampled)")
        elif REQUIRED_S3_KEYS:
            print(f"WARNING: No PDFs found for required s3_keys: {REQUIRED_S3_KEYS}")

        sampled_pdfs = []
        skipped = 0
        for row in rows:
            s3_key = row['s3_key']
            vendor_name = row['vendor_name']
            basename = Path(s3_key).name

            local_path = Path(local_dir) / basename
            if local_path.exists():
                file_path = str(local_path)
            else:
                file_path = download_file_from_s3(s3_key)
                if file_path is None:
                    logger.warning(f"Failed to download {s3_key}, skipping")
                    skipped += 1
                    continue

            sampled_pdfs.append({
                'file_path': file_path,
                'file_name': basename,
                'supplier_variation': vendor_name,
            })

        # Summarize
        vendor_counts = {}
        for pdf in sampled_pdfs:
            vendor_counts[pdf['supplier_variation']] = vendor_counts.get(pdf['supplier_variation'], 0) + 1

        print(f"Sampled {len(sampled_pdfs)} PDFs from {len(vendor_counts)} vendors (DB/S3 mode)")
        if skipped:
            print(f"  Skipped {skipped} PDFs due to download failures")
        for vendor, count in sorted(vendor_counts.items(), key=lambda x: (x[0] is None, x[0] or '')):
            print(f"  {vendor}: {count} PDFs")

        return sampled_pdfs

    def run_prompt_comparison_parallel(
            self,
            test_pdfs: List[Dict[str, Any]],
            prompts: Optional[List[PromptVariation]] = None,
            workers: int = 4,
            threads_per_worker: int = 4,
       ) -> pd.DataFrame:
        """Run prompt comparison using parallel workers"""
        if prompts is None:
            prompts = self.create_baseline_prompts()

        # Save prompts and PDF list to temp files for workers
        prompts_file = self.temp_dir / "prompts.json"
        pdfs_file = self.temp_dir / "pdfs.json"

        with open(prompts_file, 'w') as f:
            json.dump([p.to_dict() for p in prompts], f)

        with open(pdfs_file, 'w') as f:
            json.dump(test_pdfs, f)

        # Create output directory for worker results
        results_dir = self.temp_dir / "results"
        results_dir.mkdir(exist_ok=True)

        processes = []
        total_tests = len(test_pdfs) * len(prompts)

        print(f"\nRunning parallel prompt comparison:")
        print(f"  {len(prompts)} prompt variations")
        print(f"  {len(test_pdfs)} PDF samples")
        print(f"  {total_tests} total extractions")
        print(f"  {workers} parallel workers x {threads_per_worker} threads = {workers * threads_per_worker} concurrent API calls")
        print()

        # Signal handler for graceful shutdown
        def signal_handler(signum, frame):
            print(f"\nReceived signal {signum}. Shutting down workers...")
            for i, process in enumerate(processes):
                if process.poll() is None:
                    process.terminate()
            time.sleep(2)
            for i, process in enumerate(processes):
                if process.poll() is None:
                    process.kill()
            print("All workers stopped.")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            # Spawn worker processes
            for worker_id in range(workers):
                cmd = [
                    'uv', 'run',
                    'scripts/backfill_invoices_data/prompt_optimizer.py',
                    'worker',
                    '--worker-id', str(worker_id),
                    '--total-workers', str(workers),
                    '--prompts-file', str(prompts_file),
                    '--pdfs-file', str(pdfs_file),
                    '--results-dir', str(results_dir),
                    '--threads', str(threads_per_worker)
                ]

                process = subprocess.Popen(
                    cmd,
                    cwd=REPO_ROOT,
                    stdout=None,  # Show worker output in terminal
                    stderr=None,
                )
                processes.append(process)
                print(f"Started worker {worker_id}")

            print(f"\nAll {workers} workers started. Processing...")

            # Monitor workers
            while True:
                running_count = sum(1 for p in processes if p.poll() is None)
                if running_count == 0:
                    break
                time.sleep(1)

            print("All workers completed. Consolidating results...")

        except KeyboardInterrupt:
            signal_handler(signal.SIGINT, None)

        # Consolidate results
        all_results = []
        for result_file in results_dir.glob("worker_*.json"):
            with open(result_file, 'r') as f:
                worker_results = json.load(f)
                all_results.extend(worker_results)

        if not all_results:
            raise RuntimeError("No results generated by workers")

        # Convert to DataFrame and fix types from JSON round-trip
        results_df = pd.DataFrame(all_results)
        for col in ['extraction_success', 'overall_valid', 'header_valid', 'line_items_valid', 'financial_valid']:
            if col in results_df.columns:
                results_df[col] = results_df[col].astype(bool)
        for col in ['confidence_score', 'extraction_time', 'num_line_items', 'extracted_misc_charges_count', 'num_invoices_found']:
            if col in results_df.columns:
                results_df[col] = pd.to_numeric(results_df[col], errors='coerce').fillna(0)

        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save CSV for data analysis
        csv_file = self.output_dir / f"prompt_comparison_{timestamp}.csv"
        results_df.to_csv(csv_file, index=False)
        print(f"\nResults saved to:")
        print(f"  CSV: {csv_file}")

        # Save visual comparison report (like scorecard notebook)
        try:

            # Save HTML report
            html_file = self.output_dir / f"prompt_comparison_{timestamp}.html"
            create_prompt_comparison_report(results_df, html_file, format='html')
            print(f"  HTML: {html_file}")

            # Save PDF report (if weasyprint available)
            try:
                pdf_file = self.output_dir / f"prompt_comparison_{timestamp}.pdf"
                create_prompt_comparison_report(results_df, pdf_file, format='pdf')
                print(f"  PDF: {pdf_file}")
            except ImportError:
                print(f"  PDF: Skipped (install weasyprint: uv add weasyprint)")

        except ImportError:
            print(f"  Visual report: Skipped (scorecard_exporter not available)")

        return results_df

    def run_prompt_comparison_sequential(self, pdf_dir: str = None, prompts: Optional[List[PromptVariation]] = None,
                                       samples_per_supplier: int = 12,
                                       test_pdfs: Optional[List[Dict[str, Any]]] = None) -> pd.DataFrame:
        """Run prompt comparison sequentially (for testing/debugging)"""
        if prompts is None:
            prompts = self.create_baseline_prompts()

        # Use pre-sampled PDFs if provided, otherwise sample from directory
        if test_pdfs is None:
            test_pdfs = self.sample_test_pdfs(pdf_dir, samples_per_supplier)

        # Run single worker with all work
        results = self._run_worker(0, 1, prompts, test_pdfs, verbose=True)

        # Convert to DataFrame
        results_df = pd.DataFrame(results)

        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save CSV for data analysis
        csv_file = self.output_dir / f"prompt_comparison_{timestamp}.csv"
        results_df.to_csv(csv_file, index=False)
        print(f"\nResults saved to:")
        print(f"  CSV: {csv_file}")

        # Save visual comparison report (like scorecard notebook)
        try:
            # Save HTML report
            html_file = self.output_dir / f"prompt_comparison_{timestamp}.html"
            create_prompt_comparison_report(results_df, html_file, format='html')
            print(f"  HTML: {html_file}")

            # Save PDF report (if weasyprint available)
            try:
                pdf_file = self.output_dir / f"prompt_comparison_{timestamp}.pdf"
                create_prompt_comparison_report(results_df, pdf_file, format='pdf')
                print(f"  PDF: {pdf_file}")
            except ImportError:
                print(f"  PDF: Skipped (install weasyprint: uv add weasyprint)")

        except ImportError:
            print(f"  Visual report: Skipped (scorecard_exporter not available)")

        return results_df

    def _run_worker(self, worker_id: int, total_workers: int, prompts: List[PromptVariation],
                   test_pdfs: List[Dict[str, Any]], verbose: bool = False,
                   threads_per_worker: int = 4) -> List[Dict[str, Any]]:
        """Run extraction tests for assigned work using concurrent threads.

        Each worker uses a thread pool to run multiple Gemini API calls
        concurrently (I/O bound). PDF uploads and text extraction are cached
        per unique file to avoid redundant work across prompt variations.
        """

        tag = f"[W{worker_id}]"
        doc_type_ground_truth = self._doc_type_ground_truth

        # Distribute work among workers
        total_work = [(prompt, pdf) for prompt in prompts for pdf in test_pdfs]
        worker_work = [work for i, work in enumerate(total_work) if i % total_workers == worker_id]

        if verbose:
            print(f"{tag} Processing {len(worker_work)} extractions ({threads_per_worker} threads)")

        # -- Caches: upload once, extract text once per unique PDF --
        upload_cache = {}      # file_path -> uploaded_file
        raw_text_cache = {}    # file_path -> raw_pdf_text
        pdf_norm_cache = {}    # file_path -> (normalized, _)
        cache_lock = threading.Lock()

        # Build schemas per variation type (avoids sending large dicts across threads)
        # TODO: This is out of place, the PromptVariation should provide this instead of here
        schema_builders = {
            "multi": build_gemini_multi_invoice_schema,
            "classification": _build_classification_schema,
        }
        used_types = {p.schema_type for p in prompts}
        schemas = {st: builder() for st, builder in schema_builders.items() if st in used_types}

        def _get_upload(file_path: str):
            with cache_lock:
                if file_path in upload_cache:
                    return upload_cache[file_path]
            uploaded = gemini_client.files.upload(file=file_path)
            with cache_lock:
                upload_cache[file_path] = uploaded
            return uploaded

        def _get_raw_text(file_path: str):
            with cache_lock:
                if file_path in raw_text_cache:
                    return raw_text_cache[file_path]
            text = extract_text_from_pdf(file_path)
            if not text:
                text = "(Raw text extraction failed - image-based PDF)"
            with cache_lock:
                raw_text_cache[file_path] = text
            return text

        def _get_pdf_normalized(file_path: str):
            with cache_lock:
                if file_path in pdf_norm_cache:
                    return pdf_norm_cache[file_path]
            normalized = normalize_pdf_text(file_path)
            with cache_lock:
                pdf_norm_cache[file_path] = normalized
            return normalized

        # Counter for progress display
        completed_count = [0]
        count_lock = threading.Lock()

        def _run_single(work_idx: int, prompt: PromptVariation, pdf_info: Dict[str, Any]) -> Dict[str, Any]:
            """Run a single prompt variation against one PDF and return scored results.

            Sends the PDF (as both an uploaded file and raw text) to Gemini using the
            prompt's system/user instructions and response schema, then validates the
            extraction through the production `validate_and_enrich` pipeline.

            Handles two schema paths:
              - "multi": unwraps an `invoices` list, validates each invoice individually,
                and aggregates metrics (confidence averaged, validation AND-ed across all).
              - single: validates the response as one invoice directly.

            After extraction, compares the model-returned `doc_type` against ground-truth
            annotations (if available), producing per-page accuracy metrics.

            Uses closure-scoped caches (_get_upload, _get_raw_text, _get_pdf_normalized)
            for file uploads and text extraction to avoid redundant work across prompts
            targeting the same PDF.

            Args:
                work_idx: Position in the worker's task list (unused beyond ordering).
                prompt: The prompt variation (system prompt, user prompt, schema type).
                pdf_info: Dict with 'file_path', 'file_name', and 'supplier_variation'.

            Returns:
                A flat dict of scored metrics including extraction success, header/line-item/
                financial validity, confidence score, doc_type accuracy, timing, and any
                error message. Designed for direct DataFrame ingestion.
            """
            start_time = time.perf_counter()

            result = {
                'prompt_name': prompt.name,
                'prompt_hash': prompt.get_hash(),
                'file_path': pdf_info['file_path'],
                'file_name': pdf_info['file_name'],
                'supplier_variation': pdf_info['supplier_variation'],
                'extraction_success': False,
                'header_valid': False,
                'line_items_valid': False,
                'financial_valid': False,
                'overall_valid': False,
                'confidence_score': 0.0,
                'num_line_items': 0,
                'extracted_vendor': '',
                'extracted_buyer': '',
                'extracted_misc_charges_count': 0,
                'missing_header_fields': '',
                'missing_line_item_fields': '',
                'extraction_time': 0.0,
                'error_message': '',
                'raw_extraction': '',
                'num_invoices_found': 1,
                'all_ref_nos': '',
                'extracted_ref_no': '',
                'extracted_doc_type': '',
                'expected_doc_type': '',
                'doc_type_valid': False,
                'doc_type_page_accuracy': 0.0,
                'doc_type_source': '',
            }

            try:
                # Use cached uploads and text extraction
                uploaded_file = _get_upload(pdf_info['file_path'])
                raw_pdf_text = _get_raw_text(pdf_info['file_path'])

                user_prompt = prompt.user_prompt.format(raw_pdf_text=raw_pdf_text)

                # Gets the schema based on the 'schema_type' but we should be getting it out of the 
                # PromptVariation instead
                active_schema = schemas.get(prompt.schema_type, schemas["multi"])

                config = types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=active_schema,
                    system_instruction=prompt.system_prompt,
                )

                response = gemini_client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=[user_prompt, uploaded_file],
                    config=config
                )

                extracted_data = json.loads(response.text)
                if not isinstance(extracted_data, dict):
                    extracted_data = {"response": extracted_data}

                # Validate, fuzzy-correct, and enrich (same pipeline as production)
                pdf_normalized, pdf_raw_text = _get_pdf_normalized(pdf_info['file_path'])

                if isinstance(extracted_data, dict) and 'invoices' in extracted_data:
                    # Unwrap multi-invoice response
                    invoices = extracted_data.get('invoices', [extracted_data])
                    num_found = len(invoices)
                    result['num_invoices_found'] = num_found

                    all_ref_nos = []
                    validated_invoices = []
                    for inv in invoices:
                        inv['prompt_hash'] = prompt.get_hash()
                        inv = validate_and_enrich(inv, pdf_normalized, pdf_raw_text)
                        validated_invoices.append(inv)
                        ref = inv.get('ref_no', '')
                        if ref:
                            all_ref_nos.append(ref)

                    result['all_ref_nos'] = '; '.join(all_ref_nos)

                    if num_found > 1:
                        print(f"{tag} MULTI-INVOICE: {pdf_info['file_name']} -> {num_found} invoices, ref_nos: {all_ref_nos}")

                    # Store all invoices in raw_extraction for reporting
                    result['raw_extraction'] = json.dumps(
                        {"invoices": validated_invoices, "_num_invoices": num_found},
                        default=str
                    )

                    # Aggregate metrics across ALL invoices
                    if validated_invoices:
                        result['extraction_success'] = True
                        result['num_line_items'] = sum(
                            len(inv.get('line_items', [])) for inv in validated_invoices
                        )
                        def _to_float(v):
                            try:
                                return float(v)
                            except (TypeError, ValueError):
                                return 0.0
                        result['confidence_score'] = sum(
                            _to_float(inv.get('confidence_score', 0.0)) for inv in validated_invoices
                        ) / len(validated_invoices)
                        result['overall_valid'] = all(
                            inv.get('_validation_passed', False) for inv in validated_invoices
                        )
                        result['header_valid'] = all(
                            inv.get('_header_valid', False) for inv in validated_invoices
                        )
                        result['line_items_valid'] = all(
                            inv.get('_line_items_valid', False) for inv in validated_invoices
                        )
                        result['financial_valid'] = all(
                            inv.get('_financial_valid', False) for inv in validated_invoices
                        )
                        result['extracted_vendor'] = validated_invoices[0].get('vendor', '')
                        result['extracted_buyer'] = '; '.join(dict.fromkeys(
                            inv.get('buyer', '') for inv in validated_invoices
                            if inv.get('buyer', '')
                        ))
                        result['extracted_ref_no'] = '; '.join(dict.fromkeys(
                            inv.get('ref_no', '') for inv in validated_invoices
                            if inv.get('ref_no', '')
                        ))
                        result['extracted_misc_charges_count'] = sum(
                            len(inv.get('misc_charges', []) or []) for inv in validated_invoices
                        )
                        result['extracted_doc_type'] = '; '.join(
                            inv.get('doc_type', '') for inv in validated_invoices
                        )

                        # Collect missing fields across all invoices
                        all_missing_header = []
                        all_missing_line_item = []
                        for inv in validated_invoices:
                            if not inv.get('_header_valid', False):
                                all_missing_header.extend(
                                    inv.get('_header_details', {}).get('missing_fields', [])
                                )
                            if not inv.get('_line_items_valid', False):
                                all_missing_line_item.extend(
                                    inv.get('_line_items_details', {}).get('missing_fields', [])
                                )
                        if all_missing_header:
                            result['missing_header_fields'] = '; '.join(dict.fromkeys(all_missing_header))
                        if all_missing_line_item:
                            result['missing_line_item_fields'] = '; '.join(dict.fromkeys(all_missing_line_item))
                    else:
                        result['extraction_success'] = False
                        result['error_message'] = "No invoices returned by model"
                else:
                    extracted_data['prompt_hash'] = prompt.get_hash()
                    extracted_data = validate_and_enrich(extracted_data, pdf_normalized, pdf_raw_text)
                    result['raw_extraction'] = json.dumps(extracted_data, default=str)

                    result['extraction_success'] = True
                    result['confidence_score'] = extracted_data.get('confidence_score', 0.0)
                    result['num_line_items'] = len(extracted_data.get('line_items', []))
                    result['extracted_vendor'] = extracted_data.get('vendor', '')
                    result['extracted_buyer'] = extracted_data.get('buyer', '')
                    result['extracted_misc_charges_count'] = len(extracted_data.get('misc_charges', []) or [])
                    result['extracted_doc_type'] = extracted_data.get('doc_type', '')
                    result['header_valid'] = extracted_data['_header_valid']
                    result['line_items_valid'] = extracted_data['_line_items_valid']
                    result['financial_valid'] = extracted_data.get('_financial_valid', False)
                    result['overall_valid'] = extracted_data['_validation_passed']

                    if not extracted_data['_header_valid']:
                        result['missing_header_fields'] = '; '.join(
                            extracted_data.get('_header_details', {}).get('missing_fields', []))
                    if not extracted_data['_line_items_valid']:
                        result['missing_line_item_fields'] = '; '.join(
                            extracted_data.get('_line_items_details', {}).get('missing_fields', []))

                # Compare Gemini doc_type against ground truth annotations
                if result['extracted_doc_type']:
                    try:
                        file_name = pdf_info['file_name']

                        if file_name not in doc_type_ground_truth:
                            raise KeyError(f"No ground truth for {file_name}")

                        expected_types = doc_type_ground_truth[file_name]
                        result['doc_type_source'] = 'ground_truth'
                        result['expected_doc_type'] = '; '.join(expected_types)

                        # Parse Gemini doc_types and canonicalize
                        gemini_types_raw = [
                            t.strip() for t in result['extracted_doc_type'].split('; ')
                            if t.strip()
                        ]
                        gemini_types = []
                        for gt in gemini_types_raw:
                            try:
                                gemini_types.append(DocumentType(gt).canonical.value)
                            except ValueError:
                                gemini_types.append(gt)

                        # Canonicalize expected types
                        expected_canonical = []
                        for et in expected_types:
                            try:
                                expected_canonical.append(DocumentType(et).canonical.value)
                            except ValueError:
                                expected_canonical.append(et)

                        if len(expected_canonical) == 1:
                            # Single expected type: check if it appears anywhere in Gemini output
                            result['doc_type_valid'] = expected_canonical[0] in set(gemini_types)
                            result['doc_type_page_accuracy'] = 1.0 if result['doc_type_valid'] else 0.0
                        else:
                            # Multi-document: element-wise comparison
                            max_len = max(len(expected_canonical), len(gemini_types))
                            matches = sum(
                                1 for e, g in zip(expected_canonical, gemini_types)
                                if e == g
                            )
                            result['doc_type_page_accuracy'] = matches / max_len if max_len else 0.0
                            result['doc_type_valid'] = (expected_canonical == gemini_types)
                    except Exception:
                        pass  # classification failure is non-fatal

            except Exception as e:
                result['error_message'] = str(e)
                if verbose:
                    print(f"{tag} ERROR {pdf_info['file_name']} ({prompt.name}): {e}")

            result['extraction_time'] = time.perf_counter() - start_time

            if verbose:
                with count_lock:
                    completed_count[0] += 1
                    n = completed_count[0]
                status = "PASS" if result['overall_valid'] else "FAIL"
                buyer = result.get('extracted_buyer', '')
                buyer_info = f" buyer=\"{buyer}\"" if buyer else ""
                multi_info = f" invoices={result['num_invoices_found']}" if result.get('num_invoices_found', 1) > 1 else ""
                supplier = pdf_info['supplier_variation'] or 'Unknown'
                print(f"{tag} [{n}/{len(worker_work)}] {status} | {prompt.name:<25} | {supplier:<25} | {pdf_info['file_name'][:40]}{buyer_info}{multi_info} ({result['extraction_time']:.1f}s)")

            return result

        # Run extractions concurrently within this worker
        results = []
        with ThreadPoolExecutor(max_workers=threads_per_worker) as executor:
            futures = {
                executor.submit(_run_single, idx, prompt, pdf_info): idx
                for idx, (prompt, pdf_info) in enumerate(worker_work)
            }

            for future in as_completed(futures):
                results.append(future.result())

        return results

def run_worker_process(args):
    """Entry point for worker processes"""
    # Load prompts and PDFs
    with open(args.prompts_file, 'r') as f:
        prompt_dicts = json.load(f)
        prompts = [PromptVariation.from_dict(p) for p in prompt_dicts]

    with open(args.pdfs_file, 'r') as f:
        test_pdfs = json.load(f)

    # Create optimizer instance
    optimizer = PromptOptimizer()

    # Run worker with verbose output and threading
    threads = getattr(args, 'threads', 4)
    results = optimizer._run_worker(args.worker_id, args.total_workers, prompts, test_pdfs,
                                    verbose=True, threads_per_worker=threads)

    # Save results
    results_file = Path(args.results_dir) / f"worker_{args.worker_id}.json"
    with open(results_file, 'w') as f:
        json.dump(results, f)

    print(f"Worker {args.worker_id} completed {len(results)} extractions")

def analyze_results(results_df: pd.DataFrame):
    """Print analysis of results"""
    results_df = results_df.copy()

    # Coerce types -- JSON round-trip can turn bools/floats into strings
    for col in ['extraction_success', 'overall_valid', 'header_valid', 'line_items_valid', 'financial_valid']:
        if col in results_df.columns:
            results_df[col] = results_df[col].astype(bool)
    for col in ['confidence_score', 'extraction_time', 'num_line_items', 'extracted_misc_charges_count', 'num_invoices_found']:
        if col in results_df.columns:
            results_df[col] = pd.to_numeric(results_df[col], errors='coerce').fillna(0)

    print("\n" + "="*80)
    print("PROMPT COMPARISON ANALYSIS REPORT")
    print("="*80)

    print("\nOVERALL PERFORMANCE BY PROMPT:")
    print("-" * 50)

    agg_dict = {
        'extraction_success': ['count', 'sum', 'mean'],
        'overall_valid': ['sum', 'mean'],
        'header_valid': ['sum', 'mean'],
        'line_items_valid': ['sum', 'mean'],
        'confidence_score': 'mean',
        'extraction_time': 'mean',
    }
    if 'financial_valid' in results_df.columns:
        agg_dict['financial_valid'] = ['sum', 'mean']
    if 'extracted_misc_charges_count' in results_df.columns:
        agg_dict['extracted_misc_charges_count'] = 'sum'

    metrics = results_df.groupby('prompt_name').agg(agg_dict).round(3)

    for prompt_name in metrics.index:
        total = int(metrics.loc[prompt_name, ('extraction_success', 'count')])
        success = int(metrics.loc[prompt_name, ('extraction_success', 'sum')])
        overall_valid = int(metrics.loc[prompt_name, ('overall_valid', 'sum')])
        overall_rate = metrics.loc[prompt_name, ('overall_valid', 'mean')] * 100
        header_rate = metrics.loc[prompt_name, ('header_valid', 'mean')] * 100
        line_items_rate = metrics.loc[prompt_name, ('line_items_valid', 'mean')] * 100
        avg_time = metrics.loc[prompt_name, ('extraction_time', 'mean')]

        print(f"\n{prompt_name.upper()}:")
        print(f"  Success Rate: {success}/{total} ({success/total*100:.1f}%)")
        print(f"  Overall Valid: {overall_valid}/{total} ({overall_rate:.1f}%)")
        print(f"  Header Valid: {header_rate:.1f}%")
        print(f"  Line Items Valid: {line_items_rate:.1f}%")

        if 'financial_valid' in results_df.columns:
            financial_rate = metrics.loc[prompt_name, ('financial_valid', 'mean')] * 100
            print(f"  Financial Valid: {financial_rate:.1f}%")
        if 'extracted_misc_charges_count' in results_df.columns:
            misc_total = int(metrics.loc[prompt_name, ('extracted_misc_charges_count', 'sum')])
            print(f"  Total Misc Charges Found: {misc_total}")

        print(f"  Avg Time: {avg_time:.2f}s")

    # Doc type classification summary
    if 'doc_type_valid' in results_df.columns:
        results_df['doc_type_valid'] = results_df['doc_type_valid'].astype(bool)
        print("\n" + "-"*50)
        print("DOC TYPE CLASSIFICATION (Gemini vs Expected):")
        print("-" * 50)
        for prompt_name in metrics.index:
            prompt_rows = results_df[results_df['prompt_name'] == prompt_name]
            has_doc_type = prompt_rows[prompt_rows['expected_doc_type'].astype(str).str.strip().ne('')]
            if has_doc_type.empty:
                continue
            total_classified = len(has_doc_type)
            matches = has_doc_type['doc_type_valid'].sum()
            match_rate = matches / total_classified * 100
            print(f"\n  {prompt_name.upper()}:")
            print(f"    Match Rate: {int(matches)}/{total_classified} ({match_rate:.1f}%)")

            # Show page accuracy if any multi-document ground truth entries exist
            if 'doc_type_page_accuracy' in has_doc_type.columns:
                page_acc = has_doc_type['doc_type_page_accuracy'].mean() * 100
                if page_acc != match_rate:
                    print(f"    Page Accuracy: {page_acc:.1f}%")

            # Show how many files lacked ground truth
            no_gt = len(prompt_rows) - total_classified
            if no_gt > 0:
                print(f"    ({no_gt} files skipped -- no ground truth)")

            # Show distribution
            doc_types = has_doc_type['extracted_doc_type'].value_counts()
            for dt, count in doc_types.items():
                print(f"    {dt}: {count}")

    # Multi-invoice summary
    if 'num_invoices_found' in results_df.columns:
        multi = results_df[results_df['num_invoices_found'] > 1]
        if not multi.empty:
            print("\n" + "-"*50)
            print("MULTI-INVOICE DETECTIONS:")
            print("-" * 50)
            for _, row in multi.iterrows():
                print(f"  {row['prompt_name']:<25} | {row['file_name']:<45} | invoices={int(row['num_invoices_found'])} | ref_nos={row.get('all_ref_nos', '')}")

    print("\n" + "="*80)

def main():
    parser = argparse.ArgumentParser(description='Invoice prompt optimization')

    # Check if this is a worker process (has worker subcommand)
    if len(sys.argv) > 1 and sys.argv[1] == 'worker':
        subparsers = parser.add_subparsers(dest='command', help='Commands')

        # Worker command
        worker_parser = subparsers.add_parser('worker', help='Worker process')
        worker_parser.add_argument('--worker-id', type=int, required=True)
        worker_parser.add_argument('--total-workers', type=int, required=True)
        worker_parser.add_argument('--prompts-file', required=True)
        worker_parser.add_argument('--pdfs-file', required=True)
        worker_parser.add_argument('--results-dir', required=True)
        worker_parser.add_argument('--threads', type=int, default=4)

        args = parser.parse_args()
    else:
        # Main optimization command (default)
        parser.add_argument('--pdf-dir', default=None,
                            help='Directory with PDFs. If omitted, pulls most recent from DB/S3.')
        parser.add_argument('--samples-per-supplier', type=int, default=12)
        parser.add_argument('--parallel', action='store_true', help='Run in parallel')
        parser.add_argument('--workers', type=int, default=4)
        parser.add_argument('--threads', type=int, default=4, help='Concurrent threads per worker for API calls (default: 4)')
        parser.add_argument('--experiment', type=str, default=None,
                            choices=['multi-invoice'],
                            help='Run a focused experiment (e.g., multi-invoice: only baseline + multi_invoice prompts)')

        args = parser.parse_args()
        args.command = 'optimize'  # Set command manually

    if hasattr(args, 'command') and args.command == 'worker':
        run_worker_process(args)
    else:
        optimizer = PromptOptimizer()

        # Sample PDFs from directory or DB/S3
        if args.pdf_dir:
            test_pdfs = optimizer.sample_test_pdfs(args.pdf_dir, args.samples_per_supplier)
        else:
            test_pdfs = optimizer.sample_test_pdfs_from_db(args.samples_per_supplier)

        # Filter prompts if running a focused experiment
        prompts = optimizer.create_baseline_prompts()
        experiment = getattr(args, 'experiment', None)
        if experiment == 'multi-invoice':
            prompts = [p for p in prompts if p.name in ('baseline', 'multi_invoice')]
            print(f"\n-- Experiment: multi-invoice (baseline vs multi_invoice, {len(prompts)} prompts) --")

        if args.parallel:
            results_df = optimizer.run_prompt_comparison_parallel(
                prompts=prompts,
                test_pdfs=test_pdfs,
                workers=args.workers,
                threads_per_worker=args.threads
            )
        else:
            results_df = optimizer.run_prompt_comparison_sequential(
                prompts=prompts,
                test_pdfs=test_pdfs
            )

        analyze_results(results_df)

if __name__ == "__main__":
    main()
