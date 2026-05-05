"""
End-to-end test for Elementary report generation and S3 upload.

Tests three paths:
  1. Direct CLI via run_edr.py
  2. Python service function (send_report_to_s3)
  3. API endpoint POST /sync/dbt/elementary-report

Usage:
    # Run all tests (requires running server for API test):
    uv run python scripts/test_elementary_e2e.py

    # Skip API test (no server needed):
    uv run python scripts/test_elementary_e2e.py --skip-api

    # Only run CLI test:
    uv run python scripts/test_elementary_e2e.py --only cli

    # Only run service test:
    uv run python scripts/test_elementary_e2e.py --only service

    # Only run API test:
    uv run python scripts/test_elementary_e2e.py --only api
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import boto3
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

BUCKET_NAME = os.getenv("ELEMENTARY_S3_BUCKET_NAME", "")
REGION = os.getenv("ELEMENTARY_S3_REGION", "us-east-2")
ACCESS_KEY = os.getenv("PUBLIC_ACCESS_KEY", "")
SECRET_KEY = os.getenv("SECRET_ACCESS_KEY", "")
S3_OBJECT_KEY = "elementary_report.html"

DBT_PROJECT_DIR = PROJECT_ROOT / "mpi_analytics"
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"


def _redact(text: str) -> str:
    """Strip AWS credentials from output to avoid leaking into CI logs."""
    redacted = text or ""
    for secret in (ACCESS_KEY, SECRET_KEY):
        if secret:
            redacted = redacted.replace(secret, "***")
    return redacted


def get_s3_client():
    return boto3.client(
        "s3",
        region_name=REGION,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )


def get_s3_last_modified() -> str:
    """Return the LastModified timestamp of the report in S3, or empty string."""
    try:
        resp = get_s3_client().head_object(Bucket=BUCKET_NAME, Key=S3_OBJECT_KEY)
        return resp["LastModified"].isoformat()
    except Exception:
        return ""


def get_jwt_token() -> str:
    """Generate a valid admin JWT for API calls."""
    result = subprocess.run(
        [
            "uv", "run", "python", "-c",
            "from mpi_backend.utils.auth.auth_handler import signJWT; "
            "from mpi_backend.utils.auth.roles import UserRole; "
            "import psycopg2, os; "
            "conn = psycopg2.connect("
            "  host=os.getenv('POSTGRES_HOST','localhost'),"
            "  port=int(os.getenv('POSTGRES_PORT','5432')),"
            "  user=os.getenv('POSTGRES_USERNAME','woodpecker'),"
            "  password=os.getenv('POSTGRES_PASSWORD','woodpecker'),"
            "  dbname=os.getenv('POSTGRES_DB','mpi_db')); "
            "cur = conn.cursor(); "
            "cur.execute(\"SELECT id FROM users WHERE is_active=true AND role='admin' LIMIT 1\"); "
            "row = cur.fetchone(); "
            "assert row, 'No active admin user found in database'; "
            "uid = str(row[0]); conn.close(); "
            "t = signJWT(uid, UserRole.ADMIN, remember_me=True); "
            "print(t.access_token)",
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to generate JWT: {_redact(result.stderr)}")
    return result.stdout.strip()


def preflight_checks():
    """Validate required env vars before running tests."""
    missing = []
    if not BUCKET_NAME:
        missing.append("ELEMENTARY_S3_BUCKET_NAME")
    if not ACCESS_KEY:
        missing.append("PUBLIC_ACCESS_KEY")
    if not SECRET_KEY:
        missing.append("SECRET_ACCESS_KEY")
    if missing:
        print(f"{FAIL}  Missing env vars: {', '.join(missing)}")
        print("       Set them in .env and re-run.")
        sys.exit(1)

    try:
        get_s3_client().head_bucket(Bucket=BUCKET_NAME)
    except Exception as e:
        print(f"{FAIL}  Cannot reach S3 bucket '{BUCKET_NAME}': {e}")
        sys.exit(1)

    print(f"  Bucket:  {BUCKET_NAME}")
    print(f"  Region:  {REGION}")
    print(f"  Object:  {S3_OBJECT_KEY}")
    print()


# ---------------------------------------------------------------------------
# Test 1: CLI via run_edr.py
# ---------------------------------------------------------------------------
def test_cli():
    print("=" * 60)
    print("TEST 1: CLI  (uv run python run_edr.py send-report)")
    print("=" * 60)

    before = get_s3_last_modified()

    cmd = [
        "uv", "run", "python", "run_edr.py", "send-report",
        "--project-dir", ".",
        "--profiles-dir", ".",
        "--profile-target", "dev",
        "--s3-bucket-name", BUCKET_NAME,
        "--aws-access-key-id", ACCESS_KEY,
        "--aws-secret-access-key", SECRET_KEY,
        "--aws-region-name", REGION,
        "--bucket-file-path", S3_OBJECT_KEY,
    ]

    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(DBT_PROJECT_DIR))
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"  {FAIL}  edr exited with code {result.returncode}")
        print(f"         stderr: {_redact(result.stderr[-500:])}")
        return False

    after = get_s3_last_modified()
    if after and after != before:
        print(f"  {PASS}  Report uploaded to S3 ({elapsed:.1f}s)")
        print(f"         LastModified: {after}")
        return True
    elif after == before and before:
        print(f"  {FAIL}  S3 object was not updated (LastModified unchanged)")
        return False
    else:
        print(f"  {FAIL}  Could not verify S3 object after upload")
        return False


# ---------------------------------------------------------------------------
# Test 2: Python service function
# ---------------------------------------------------------------------------
def test_service():
    print()
    print("=" * 60)
    print("TEST 2: Service  (send_report_to_s3())")
    print("=" * 60)

    before = get_s3_last_modified()

    result = subprocess.run(
        [
            "uv", "run", "python", "-c",
            "from mpi_backend.utils.elementary_report_service import send_report_to_s3; "
            "r = send_report_to_s3(); "
            "print('OK:' + str(r) if r else 'FAIL:None')",
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    if result.returncode != 0:
        print(f"  {FAIL}  Python process exited with code {result.returncode}")
        print(f"         stderr: {_redact(result.stderr[-500:])}")
        return False

    output = result.stdout.strip()
    if output.startswith("OK:"):
        after = get_s3_last_modified()
        if after and after != before:
            print(f"  {PASS}  send_report_to_s3() returned: {output[3:]}")
            print(f"         LastModified: {after}")
            return True
        else:
            print(f"  {FAIL}  Function returned OK but S3 object not updated")
            return False
    else:
        print(f"  {FAIL}  send_report_to_s3() returned None")
        print(f"         stdout: {_redact(output)}")
        print(f"         stderr: {_redact(result.stderr[-500:])}")
        return False


# ---------------------------------------------------------------------------
# Test 3: API endpoint
# ---------------------------------------------------------------------------
def test_api():
    print()
    print("=" * 60)
    print("TEST 3: API   (POST /sync/dbt/elementary-report)")
    print("=" * 60)

    try:
        requests.get(f"{BASE_URL}/docs", timeout=3)
    except requests.RequestException:
        print(f"  {SKIP}  Server not reachable at {BASE_URL}")
        print("         Start with: uv run uvicorn mpi_backend.main:app --port 8000")
        return None

    before = get_s3_last_modified()

    try:
        token = get_jwt_token()
    except RuntimeError as e:
        print(f"  {FAIL}  {e}")
        return False

    resp = requests.post(
        f"{BASE_URL}/sync/dbt/elementary-report",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )

    if resp.status_code != 200:
        print(f"  {FAIL}  HTTP {resp.status_code}: {_redact(resp.text)}")
        return False

    body = resp.json()
    status = body.get("status")

    if status == "skipped":
        print(f"  {SKIP}  {body.get('message')} -- retry after dbt finishes")
        return None

    if status != "started":
        print(f"  {FAIL}  Unexpected status: {json.dumps(body)}")
        return False

    print(f"  Accepted: {body.get('message')}")
    print("  Waiting for background task to complete...")

    for i in range(12):
        time.sleep(5)
        after = get_s3_last_modified()
        if after and after != before:
            print(f"  {PASS}  S3 object updated after ~{(i + 1) * 5}s")
            print(f"         LastModified: {after}")
            return True
        print(f"         ...{(i + 1) * 5}s elapsed, still waiting")

    print(f"  {FAIL}  S3 object not updated after 60s")
    return False


def main():
    parser = argparse.ArgumentParser(description="Elementary E2E test")
    parser.add_argument("--skip-api", action="store_true", help="Skip the API endpoint test")
    parser.add_argument("--only", choices=["cli", "service", "api"], help="Run only one test")
    args = parser.parse_args()

    print()
    print("Elementary E2E Test Suite")
    print("-" * 60)
    preflight_checks()

    results = {}

    if args.only in (None, "cli"):
        results["cli"] = test_cli()
    if args.only in (None, "service"):
        results["service"] = test_service()
    if args.only in (None, "api") and not args.skip_api:
        results["api"] = test_api()

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, result in results.items():
        tag = PASS if result is True else (SKIP if result is None else FAIL)
        print(f"  {tag}  {name}")

    failures = sum(1 for r in results.values() if r is False)
    if failures:
        print(f"\n{failures} test(s) failed.")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
