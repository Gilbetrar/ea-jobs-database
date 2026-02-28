#!/usr/bin/env python3
"""Test script for Issue #2: Parse EA Slack Export.

Exit code 0 = all tests pass, non-zero = failure.

Tier 1: Deterministic tests (MUST pass)
Tier 2: Integration tests (warnings only)
"""

import glob
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

passed = 0
failed = 0
warnings = 0


def tier1_pass(msg):
    global passed
    passed += 1
    print(f"  PASS: {msg}")


def tier1_fail(msg):
    global failed
    failed += 1
    print(f"  FAIL: {msg}")


def tier2_warn(msg):
    global warnings
    warnings += 1
    print(f"  WARN: {msg}")


def tier2_pass(msg):
    global passed
    passed += 1
    print(f"  PASS: {msg}")


# ===== TIER 1: Deterministic Tests =====
print("\n=== TIER 1: Deterministic Tests ===\n")


# --- Test 1: Slack export path configuration ---
print("Test 1: Slack export path configuration")
config_path = os.environ.get("EA_SLACK_EXPORT_PATH")
if not config_path:
    config_file = PROJECT_ROOT / "config.json"
    if config_file.is_file():
        with open(config_file) as f:
            config_path = json.load(f).get("slack_export_path")

if config_path and os.path.isfile(config_path):
    tier1_pass(f"Slack export configured: {config_path}")
else:
    tier2_warn("Slack export path not configured (needed for full parser run)")


# --- Test 2: Parser script exists ---
print("Test 2: Parser script exists")
parser_path = PROJECT_ROOT / "scripts" / "parse_slack_export.py"
if parser_path.is_file():
    tier1_pass("scripts/parse_slack_export.py exists")
else:
    tier1_fail("scripts/parse_slack_export.py missing")


# --- Test 3: Parser fails fast without config ---
print("Test 3: Parser fails fast without config")
env_clean = {k: v for k, v in os.environ.items() if k != "EA_SLACK_EXPORT_PATH"}
result = subprocess.run(
    [sys.executable, str(parser_path)],
    capture_output=True, text=True, env=env_clean,
    cwd=str(PROJECT_ROOT / "tests")  # Run from a dir without config.json
)
if result.returncode != 0 and "not configured" in result.stderr.lower():
    tier1_pass("Parser fails fast with clear error when no config")
else:
    tier1_fail(f"Parser should fail without config. rc={result.returncode}, stderr={result.stderr[:200]}")


# --- Test 4: Test fixture exists ---
print("Test 4: Test fixture exists")
fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "sample_slack.md"
if fixture_path.is_file():
    tier1_pass("tests/fixtures/sample_slack.md exists")
else:
    tier1_fail("tests/fixtures/sample_slack.md missing")


# --- Test 5: Fixture test — parse sample, compare to expected ---
print("Test 5: Fixture parse produces expected output")

# Use a temp directory for fixture output to avoid polluting data/
with tempfile.TemporaryDirectory() as tmpdir:
    tmp_jobs = Path(tmpdir) / "data" / "jobs"
    tmp_orgs = Path(tmpdir) / "data" / "orgs"
    tmp_exports = Path(tmpdir) / "exports"
    tmp_jobs.mkdir(parents=True)
    tmp_orgs.mkdir(parents=True)
    tmp_exports.mkdir(parents=True)

    # Import and run parser directly
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import parse_slack_export as parser

    # Override output directories
    orig_jobs = parser.DATA_JOBS
    orig_orgs = parser.DATA_ORGS
    orig_exports = parser.EXPORTS
    parser.DATA_JOBS = tmp_jobs
    parser.DATA_ORGS = tmp_orgs
    parser.EXPORTS = tmp_exports

    try:
        all_jobs, all_orgs, stats = parser.parse_export(str(fixture_path))
        parser.write_outputs(all_jobs, all_orgs, stats)

        # Compare jobs
        expected_jobs_path = PROJECT_ROOT / "tests" / "fixtures" / "expected_jobs.json"
        if expected_jobs_path.is_file():
            with open(expected_jobs_path) as f:
                expected_jobs = json.load(f)

            actual_job_files = sorted(glob.glob(str(tmp_jobs / "*.json")))
            actual_jobs = []
            for jf in actual_job_files:
                with open(jf) as f:
                    actual_jobs.append(json.load(f))
            actual_jobs.sort(key=lambda x: x["id"])
            expected_jobs.sort(key=lambda x: x["id"])

            # Fields that change per run (date_added = today's date)
            SKIP_FIELDS = {"date_added"}

            if len(actual_jobs) == len(expected_jobs):
                job_match = True
                for actual, expected in zip(actual_jobs, expected_jobs):
                    # Compare all fields except dynamic ones
                    for key in set(list(actual.keys()) + list(expected.keys())):
                        if key in SKIP_FIELDS:
                            # Just verify the field exists and is a valid date
                            if key == "date_added" and not actual.get(key):
                                tier1_fail(f"Job {actual.get('id', '?')}: missing date_added")
                                job_match = False
                            continue
                        if actual.get(key) != expected.get(key):
                            job_match = False
                            tier1_fail(
                                f"Job {actual.get('id', '?')}: field '{key}' "
                                f"expected {expected.get(key)!r}, got {actual.get(key)!r}"
                            )
                            break
                    if not job_match:
                        break
                if job_match:
                    tier1_pass(f"All {len(actual_jobs)} fixture jobs match expected output")
            else:
                tier1_fail(f"Expected {len(expected_jobs)} jobs, got {len(actual_jobs)}")
        else:
            tier1_fail("Missing expected_jobs.json fixture")

        # Compare orgs
        expected_orgs_path = PROJECT_ROOT / "tests" / "fixtures" / "expected_orgs.json"
        if expected_orgs_path.is_file():
            with open(expected_orgs_path) as f:
                expected_orgs = json.load(f)

            actual_org_files = sorted(glob.glob(str(tmp_orgs / "*.json")))
            actual_orgs = []
            for of in actual_org_files:
                with open(of) as f:
                    actual_orgs.append(json.load(f))
            actual_orgs.sort(key=lambda x: x["id"])
            expected_orgs.sort(key=lambda x: x["id"])

            if len(actual_orgs) == len(expected_orgs):
                org_match = True
                for actual, expected in zip(actual_orgs, expected_orgs):
                    if actual != expected:
                        org_match = False
                        for key in set(list(actual.keys()) + list(expected.keys())):
                            if actual.get(key) != expected.get(key):
                                tier1_fail(
                                    f"Org {actual.get('id', '?')}: field '{key}' "
                                    f"expected {expected.get(key)!r}, got {actual.get(key)!r}"
                                )
                        break
                if org_match:
                    tier1_pass(f"All {len(actual_orgs)} fixture orgs match expected output")
            else:
                tier1_fail(f"Expected {len(expected_orgs)} orgs, got {len(actual_orgs)}")
        else:
            tier1_fail("Missing expected_orgs.json fixture")

        # Check stats
        if stats["total_posts"] > 0:
            tier1_pass(f"Parser processed {stats['total_posts']} posts")
        else:
            tier1_fail("Parser found 0 posts in fixture")

        if stats["skipped"] > 0:
            tier1_pass(f"Parser correctly skipped {stats['skipped']} non-job posts")
        else:
            tier1_fail("Parser should have skipped at least 1 non-job post")

        # Check summary report
        report_files = glob.glob(str(tmp_exports / "*summary*")) + glob.glob(str(tmp_exports / "*report*"))
        if report_files:
            with open(report_files[0]) as f:
                report = f.read().lower()
            missing_fields = []
            for field in ["total", "found", "skipped", "low-confidence"]:
                if field not in report:
                    missing_fields.append(field)
            if not missing_fields:
                tier1_pass("Summary report contains all required fields")
            else:
                tier1_fail(f"Summary report missing fields: {missing_fields}")
        else:
            tier1_fail("No summary report found in exports/")

    finally:
        # Restore original paths
        parser.DATA_JOBS = orig_jobs
        parser.DATA_ORGS = orig_orgs
        parser.EXPORTS = orig_exports


# --- Test 6: Idempotency test ---
print("Test 6: Idempotency test")

with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
    for tmpdir, label in [(tmpdir1, "run1"), (tmpdir2, "run2")]:
        tmp_jobs = Path(tmpdir) / "data" / "jobs"
        tmp_orgs = Path(tmpdir) / "data" / "orgs"
        tmp_exports = Path(tmpdir) / "exports"
        tmp_jobs.mkdir(parents=True)
        tmp_orgs.mkdir(parents=True)
        tmp_exports.mkdir(parents=True)

        parser.DATA_JOBS = tmp_jobs
        parser.DATA_ORGS = tmp_orgs
        parser.EXPORTS = tmp_exports

        all_jobs, all_orgs, stats = parser.parse_export(str(fixture_path))
        parser.write_outputs(all_jobs, all_orgs, stats)

    # Restore paths
    parser.DATA_JOBS = orig_jobs
    parser.DATA_ORGS = orig_orgs
    parser.EXPORTS = orig_exports

    # Compare file hashes
    def hash_dir(d):
        hashes = {}
        for f in sorted(glob.glob(str(Path(d) / "**" / "*"), recursive=True)):
            if os.path.isfile(f):
                rel = os.path.relpath(f, d)
                with open(f, "rb") as fh:
                    hashes[rel] = hashlib.md5(fh.read()).hexdigest()
        return hashes

    hashes1 = hash_dir(tmpdir1)
    hashes2 = hash_dir(tmpdir2)

    if hashes1 == hashes2:
        tier1_pass("Parser is idempotent (two runs produce identical output)")
    else:
        diff_files = set(hashes1.keys()) ^ set(hashes2.keys())
        diff_content = {k for k in hashes1 if k in hashes2 and hashes1[k] != hashes2[k]}
        tier1_fail(f"Parser is NOT idempotent. Diff files: {diff_files}, Changed: {diff_content}")


# --- Test 7: Schema validation of fixture output ---
print("Test 7: Schema validation")
try:
    import jsonschema

    job_schema_path = PROJECT_ROOT / "schemas" / "job.schema.json"
    org_schema_path = PROJECT_ROOT / "schemas" / "org.schema.json"

    with open(job_schema_path) as f:
        job_schema = json.load(f)
    with open(org_schema_path) as f:
        org_schema = json.load(f)

    # Validate the fixture-generated jobs
    expected_jobs_path = PROJECT_ROOT / "tests" / "fixtures" / "expected_jobs.json"
    with open(expected_jobs_path) as f:
        fixture_jobs = json.load(f)

    job_errors = 0
    for job in fixture_jobs:
        try:
            jsonschema.validate(job, job_schema)
        except jsonschema.ValidationError as e:
            tier1_fail(f"Job {job['id']} fails schema: {e.message}")
            job_errors += 1

    if job_errors == 0:
        tier1_pass(f"All {len(fixture_jobs)} fixture jobs validate against schema")

    # Validate the fixture-generated orgs
    expected_orgs_path = PROJECT_ROOT / "tests" / "fixtures" / "expected_orgs.json"
    with open(expected_orgs_path) as f:
        fixture_orgs = json.load(f)

    org_errors = 0
    for org in fixture_orgs:
        try:
            jsonschema.validate(org, org_schema)
        except jsonschema.ValidationError as e:
            tier1_fail(f"Org {org['id']} fails schema: {e.message}")
            org_errors += 1

    if org_errors == 0:
        tier1_pass(f"All {len(fixture_orgs)} fixture orgs validate against schema")

except ImportError:
    tier1_fail("jsonschema not installed (pip3 install jsonschema)")


# --- Test 8: Low-confidence records have notes ---
print("Test 8: Low-confidence records have notes")
low_conf_without_notes = []
for job in fixture_jobs:
    if job.get("confidence", 1.0) < 0.5 and not job.get("notes"):
        low_conf_without_notes.append(job["id"])

if low_conf_without_notes:
    tier1_fail(f"Low-confidence records missing notes: {low_conf_without_notes}")
else:
    tier1_pass("All low-confidence records have explanatory notes (or none exist)")


# ===== TIER 2: Integration Tests =====
print("\n=== TIER 2: Integration Tests ===\n")


# --- Test 9: Full parser run on real data ---
print("Test 9: Full parser run on real Slack export")
if config_path and os.path.isfile(str(config_path)):
    try:
        result = subprocess.run(
            [sys.executable, str(parser_path), str(config_path)],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT)
        )
        if result.returncode == 0:
            tier2_pass(f"Full parser run succeeded")

            # Check output counts
            job_files = glob.glob(str(PROJECT_ROOT / "data" / "jobs" / "*.json"))
            org_files = glob.glob(str(PROJECT_ROOT / "data" / "orgs" / "*.json"))

            if len(job_files) >= 80:
                tier2_pass(f"Found {len(job_files)} job files (>= 80)")
            else:
                tier2_warn(f"Found {len(job_files)} job files (expected >= 80)")

            if len(org_files) >= 50:
                tier2_pass(f"Found {len(org_files)} org files (>= 50)")
            else:
                tier2_warn(f"Found {len(org_files)} org files (expected >= 50)")
        else:
            tier2_warn(f"Full parser run failed: {result.stderr[:200]}")
    except Exception as e:
        tier2_warn(f"Full parser run error: {e}")
else:
    tier2_warn("Skipped: Slack export file not configured or not found")


# ===== Summary =====
print(f"\n{'=' * 40}")
print(f"Results: {passed} passed, {failed} failed, {warnings} warnings")
print(f"{'=' * 40}")

if failed > 0:
    print("\nFAILED")
    sys.exit(1)
else:
    print("\nPASSED")
    sys.exit(0)
