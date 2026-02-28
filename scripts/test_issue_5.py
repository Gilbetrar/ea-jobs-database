#!/usr/bin/env python3
"""Test script for Issue #5: 80K Hours Ingestion via Algolia API.

Validates all deliverables. Exit code 0 = pass, non-zero = fail.

Tier 1 tests are deterministic and MUST all pass.
Tier 2 tests are integration tests (API-dependent) — failures are warnings only.
"""

import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Add scripts dir to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

TESTS_DIR = PROJECT_ROOT / "tests" / "fixtures"
DATA_JOBS = PROJECT_ROOT / "data" / "jobs"
DATA_ORGS = PROJECT_ROOT / "data" / "orgs"
DATA_JDS = PROJECT_ROOT / "data" / "jds"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"

passed = 0
failed = 0
warnings = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        if detail:
            print(f"        {detail}")
        failed += 1


def warn(name, condition, detail=""):
    global passed, warnings
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  WARN: {name}")
        if detail:
            print(f"        {detail}")
        warnings += 1


# -----------------------------------------------------------------------
# Tier 1 — Deterministic (MUST all pass)
# -----------------------------------------------------------------------

print("\n=== Tier 1: Deterministic Tests ===\n")

# 1. Script exists and is importable
print("[1] Script exists and is importable")
script_path = PROJECT_ROOT / "scripts" / "fetch_80k_hours.py"
test("fetch_80k_hours.py exists", script_path.exists())

try:
    from fetch_80k_hours import (
        convert_job, convert_company, html_to_markdown,
        slugify, parse_salary, make_job_id,
        check_api_connectivity, main
    )
    test("Script imports successfully", True)
except ImportError as e:
    test("Script imports successfully", False, str(e))
    print("\nCANNOT CONTINUE — script won't import")
    sys.exit(1)

# 2. Fixture test — Algolia record conversion
print("\n[2] Algolia record conversion fixture test")
fixture_path = TESTS_DIR / "sample_algolia_record.json"
expected_path = TESTS_DIR / "sample_algolia_expected.json"
test("sample_algolia_record.json exists", fixture_path.exists())
test("sample_algolia_expected.json exists", expected_path.exists())

if fixture_path.exists() and expected_path.exists():
    fixture = json.load(open(fixture_path))
    expected = json.load(open(expected_path))
    job, jd_md = convert_job(fixture)

    # Compare field by field (skip date_added which varies)
    for key in expected:
        if key == "date_added":
            continue
        actual = job.get(key)
        exp = expected[key]
        test(f"Field '{key}' matches", actual == exp,
             f"expected {exp!r}, got {actual!r}" if actual != exp else "")

    test("JD markdown is non-empty", len(jd_md) > 0)
    test("Job source is '80k-hours'", job.get("source") == "80k-hours")
    test("Job confidence is 1.0", job.get("confidence") == 1.0)

# 3. HTML-to-markdown fixture test
print("\n[3] HTML-to-markdown conversion fixture test")
html_fixture_path = TESTS_DIR / "sample_jd_html.html"
md_expected_path = TESTS_DIR / "sample_jd_expected.md"
test("sample_jd_html.html exists", html_fixture_path.exists())
test("sample_jd_expected.md exists", md_expected_path.exists())

if html_fixture_path.exists() and md_expected_path.exists():
    html_input = open(html_fixture_path).read()
    expected_md = open(md_expected_path).read().strip()
    actual_md = html_to_markdown(html_input)

    # Normalize whitespace for comparison
    def normalize(text):
        lines = [line.rstrip() for line in text.strip().splitlines()]
        return "\n".join(lines)

    test("HTML-to-markdown output matches expected",
         normalize(actual_md) == normalize(expected_md),
         f"Output differs from expected")

# 4. Count verification by source field
print("\n[4] Count verification (source='80k-hours')")
job_files = glob.glob(str(DATA_JOBS / "*.json"))
jobs_80k = []
for f in job_files:
    try:
        data = json.load(open(f))
        if data.get("source") == "80k-hours":
            jobs_80k.append(f)
    except (json.JSONDecodeError, KeyError):
        pass

test(f"At least 700 jobs with source='80k-hours' (got {len(jobs_80k)})",
     len(jobs_80k) >= 700)

# 5. All output validates against schemas
print("\n[5] Schema validation")
try:
    import jsonschema
    job_schema = json.load(open(SCHEMAS_DIR / "job.schema.json"))
    org_schema = json.load(open(SCHEMAS_DIR / "org.schema.json"))

    job_errors = 0
    for f in job_files:
        try:
            data = json.load(open(f))
            jsonschema.validate(data, job_schema)
        except (jsonschema.ValidationError, json.JSONDecodeError) as e:
            job_errors += 1
            if job_errors <= 3:
                print(f"    Schema error in {Path(f).name}: {e.message if hasattr(e, 'message') else e}")

    test(f"All {len(job_files)} job files validate against schema ({job_errors} errors)",
         job_errors == 0)

    org_files = glob.glob(str(DATA_ORGS / "*.json"))
    org_errors = 0
    for f in org_files:
        try:
            data = json.load(open(f))
            jsonschema.validate(data, org_schema)
        except (jsonschema.ValidationError, json.JSONDecodeError) as e:
            org_errors += 1
            if org_errors <= 3:
                print(f"    Schema error in {Path(f).name}: {e.message if hasattr(e, 'message') else e}")

    test(f"All {len(org_files)} org files validate against schema ({org_errors} errors)",
         org_errors == 0)

except ImportError:
    test("jsonschema installed", False, "pip3 install jsonschema")

# 6. --dry-run writes zero files
print("\n[6] Dry-run test")
files_before = set(glob.glob(str(DATA_JOBS / "*.json")) + glob.glob(str(DATA_JDS / "*.md")))
result = subprocess.run(
    [sys.executable, str(script_path), "--dry-run"],
    capture_output=True, text=True, timeout=60
)
files_after = set(glob.glob(str(DATA_JOBS / "*.json")) + glob.glob(str(DATA_JDS / "*.md")))
test("Dry run exits 0", result.returncode == 0,
     f"Exit code: {result.returncode}, stderr: {result.stderr[:200]}")
test("Dry run writes zero files", files_before == files_after,
     f"File count changed: {len(files_before)} -> {len(files_after)}")

# 7. --since flag accepted
print("\n[7] --since flag test")
result = subprocess.run(
    [sys.executable, str(script_path), "--since", "2026-02-01", "--dry-run"],
    capture_output=True, text=True, timeout=60
)
test("--since flag accepted (exit 0)", result.returncode == 0,
     f"Exit code: {result.returncode}, stderr: {result.stderr[:200]}")

# 8. --help includes required flags
print("\n[8] --help output test")
result = subprocess.run(
    [sys.executable, str(script_path), "--help"],
    capture_output=True, text=True, timeout=30
)
test("--help exits 0", result.returncode == 0)
test("--since in help output", "--since" in result.stdout)
test("--dry-run in help output", "--dry-run" in result.stdout)

# 9. JD files have frontmatter
print("\n[9] JD file frontmatter test")
jd_files = glob.glob(str(DATA_JDS / "*.md"))
if jd_files:
    sample_jd = open(jd_files[0]).read()
    test("JD files exist", len(jd_files) > 0)
    test("JD has YAML frontmatter", sample_jd.startswith("---"))
    test("JD frontmatter has job_id", "job_id:" in sample_jd)
    test("JD frontmatter has fetched_date", "fetched_date:" in sample_jd)
    test("JD frontmatter has platform", "platform:" in sample_jd)
else:
    test("JD files exist", False)

# 10. Helper function tests
print("\n[10] Helper function tests")
test("slugify('80,000 Hours') => '80000-hours'",
     slugify("80,000 Hours") == "80000-hours")
test("slugify('Blueprint Biosecurity') => 'blueprint-biosecurity'",
     slugify("Blueprint Biosecurity") == "blueprint-biosecurity")
test("parse_salary('$140,000 - $170,000') has min/max",
     parse_salary("$140,000 - $170,000") is not None and
     parse_salary("$140,000 - $170,000")["min"] == 140000.0)
test("parse_salary('$40 - $74 per hour') returns None (hourly)",
     parse_salary("$40 - $74 per hour") is None)
test("parse_salary('') returns None",
     parse_salary("") is None)
test("make_job_id works",
     make_job_id("org", "title", "2026-02") == "org--title--2026-02")


# -----------------------------------------------------------------------
# Tier 2 — Integration (failures are warnings, not blockers)
# -----------------------------------------------------------------------

print("\n=== Tier 2: Integration Tests (warnings only) ===\n")

# 1. API connectivity test
print("[T2-1] API connectivity")
try:
    from algoliasearch.search.client import SearchClientSync
    client = SearchClientSync("W6KM1UDIB3", "d1d7f2c8696e7b36837d5ed337c4a319")
    result = client.search_single_index("jobs_prod_super_ranked", {"hitsPerPage": 1})
    warn("Algolia API accessible", result.hits is not None and len(result.hits) > 0,
         "API returned no results")
    print(f"    INFO: {result.nb_hits} total jobs in index")
except Exception as e:
    warn("Algolia API accessible", False, f"API error: {e}")

# 2. Full count verification
print("\n[T2-2] Full count verification")
try:
    count = len(jobs_80k)
    warn(f"80K Hours jobs count ({count}) reasonable (>= 700)",
         count >= 700, f"Got {count}")
except Exception as e:
    warn("Count verification", False, str(e))

# 3. Orgs created
print("\n[T2-3] Organization data")
org_files = glob.glob(str(DATA_ORGS / "*.json"))
warn(f"Multiple org files exist ({len(org_files)})",
     len(org_files) > 10, f"Only {len(org_files)} org files")


# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------

print("\n" + "=" * 50)
print(f"Results: {passed} passed, {failed} failed, {warnings} warnings")
print("=" * 50)

if failed > 0:
    print("\nFAILED — some Tier 1 tests did not pass")
    sys.exit(1)
else:
    if warnings > 0:
        print(f"\nPASSED (with {warnings} Tier 2 warnings)")
    else:
        print("\nPASSED — all tests green")
    sys.exit(0)
