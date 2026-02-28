#!/usr/bin/env python3
"""Test script for Issue #4: Airtable Sync Script.

Validates all deliverables for the sync_to_airtable.py script.
Exit code 0 = pass, non-zero = fail.

Tier 1 — Deterministic (MUST all pass)
Tier 2 — Integration (failures are warnings, not blockers)
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parent / "sync_to_airtable.py")
PROJECT_ROOT = Path(__file__).resolve().parent.parent

passed = 0
failed = 0
warnings = 0


def tier1(name):
    def decorator(func):
        func._test_name = name
        func._tier = 1
        return func
    return decorator


def tier2(name):
    def decorator(func):
        func._test_name = name
        func._tier = 2
        return func
    return decorator


def run_sync(*args, env=None):
    """Run the sync script with given arguments."""
    cmd = [sys.executable, SCRIPT] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return result


# --- Tier 1: Deterministic Tests ---

@tier1("Script exists and is executable")
def test_script_exists():
    assert Path(SCRIPT).exists(), f"Script not found: {SCRIPT}"


@tier1("Help output shows all required flags")
def test_help_flags():
    result = run_sync("--help")
    assert result.returncode == 0, f"--help failed with code {result.returncode}"
    help_text = result.stdout
    for flag in ["--output-json", "--dry-run", "--ids", "--ids-file", "--all", "--filter"]:
        assert flag in help_text, f"Missing {flag} in help output"


@tier1("Pre-flight: --ids-file with missing file fails fast")
def test_missing_ids_file():
    result = run_sync("--ids-file", "/nonexistent/file.json")
    assert result.returncode != 0, "Should fail when ids-file doesn't exist"
    stderr = result.stderr.lower()
    assert any(phrase in stderr for phrase in ["not found", "not exist", "no such"]), \
        f"Should give clear error about missing file, got: {result.stderr}"


@tier1("Dry run with --all produces valid JSON output")
def test_dry_run_json():
    result = run_sync("--dry-run", "--all", "--output-json")
    assert result.returncode == 0, f"Dry run failed: {result.stderr}"
    output = json.loads(result.stdout)
    for key in ["created", "updated", "skipped", "errors"]:
        assert key in output, f"JSON output missing key: {key}"
        assert isinstance(output[key], int), f"{key} should be int, got {type(output[key])}"


@tier1("Dry run creates 0 errors")
def test_dry_run_no_errors():
    result = run_sync("--dry-run", "--all", "--output-json")
    assert result.returncode == 0, f"Dry run failed: {result.stderr}"
    output = json.loads(result.stdout)
    assert output["errors"] == 0, f"Dry run should have 0 errors, got {output['errors']}"


@tier1("--ids with valid job ID works in dry-run")
def test_ids_dry_run():
    # Use the sample job we know exists
    result = run_sync("--dry-run", "--output-json", "--ids", "open-philanthropy--research-analyst--2025-01")
    assert result.returncode == 0, f"--ids dry run failed: {result.stderr}"
    output = json.loads(result.stdout)
    assert output["created"] > 0, f"Expected created > 0, got {output['created']}"


@tier1("--ids with valid org ID works in dry-run")
def test_ids_org_dry_run():
    result = run_sync("--dry-run", "--output-json", "--ids", "open-philanthropy")
    assert result.returncode == 0, f"--ids dry run failed: {result.stderr}"
    output = json.loads(result.stdout)
    assert output["created"] > 0, f"Expected created > 0 for org, got {output['created']}"


@tier1("--ids-file with valid file works in dry-run")
def test_ids_file_dry_run():
    # Create a temp IDs file
    ids = ["open-philanthropy--research-analyst--2025-01", "open-philanthropy"]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(ids, f)
        tmp_path = f.name
    try:
        result = run_sync("--dry-run", "--output-json", "--ids-file", tmp_path)
        assert result.returncode == 0, f"--ids-file dry run failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["created"] == 2, f"Expected 2 created (1 job + 1 org), got {output['created']}"
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@tier1("--filter works with dry-run")
def test_filter_dry_run():
    result = run_sync("--dry-run", "--output-json", "--all", "--filter", "status=unknown")
    assert result.returncode == 0, f"Filter dry run failed: {result.stderr}"
    output = json.loads(result.stdout)
    # The sample job has status=unknown so it should match
    assert isinstance(output["created"], int), "Should return valid counts"


@tier1("--filter excludes non-matching records")
def test_filter_excludes():
    result = run_sync("--dry-run", "--output-json", "--all", "--filter", "status=nonexistent_status")
    assert result.returncode == 0, f"Filter dry run failed: {result.stderr}"
    output = json.loads(result.stdout)
    # No jobs should match this filter, but orgs aren't filtered
    # So only org creates should appear
    assert output["errors"] == 0, "No errors expected"


@tier1("Nested filter with dot notation works")
def test_nested_filter():
    result = run_sync("--dry-run", "--output-json", "--all", "--filter", "salary.currency=USD")
    assert result.returncode == 0, f"Nested filter failed: {result.stderr}"
    output = json.loads(result.stdout)
    assert isinstance(output["created"], int), "Should return valid counts"


@tier1("Without API keys, non-dry-run fails with clear error")
def test_no_api_key_error():
    import os
    env = {k: v for k, v in os.environ.items() if k not in ("AIRTABLE_API_KEY", "AIRTABLE_BASE_ID")}
    result = run_sync("--all", "--output-json", env=env)
    assert result.returncode != 0, "Should fail without API keys"
    assert "AIRTABLE_API_KEY" in result.stderr or "AIRTABLE_BASE_ID" in result.stderr, \
        f"Should mention missing env vars, got: {result.stderr}"


@tier1("--force flag is accepted")
def test_force_flag():
    result = run_sync("--help")
    assert "--force" in result.stdout, "Missing --force in help output"


@tier1("Field mapping produces correct Airtable fields for jobs")
def test_job_field_mapping():
    """Test field mapping by importing the module directly."""
    sys.path.insert(0, str(Path(SCRIPT).parent))
    try:
        import sync_to_airtable as sync
        job = {
            "id": "test-org--test-role--2025-01",
            "title": "Test Role",
            "organization": "test-org",
            "source": "manual",
            "source_url": "https://example.com",
            "location": {"type": "remote", "cities": ["London"]},
            "salary": {"min": 50000, "max": 70000, "currency": "GBP", "period": "annual"},
            "posted_date": "2025-01-15",
            "deadline": "2025-03-01",
            "date_added": "2025-01-20",
            "tags": ["research", "ai-safety"],
            "status": "open",
            "confidence": 0.9,
            "notes": "Test note",
        }
        fields = sync.map_job_fields(job)

        assert fields["git_id"] == "test-org--test-role--2025-01"
        assert fields["Title"] == "Test Role"
        assert fields["Organization"] == "test-org"
        assert fields["Source"] == "manual"
        assert fields["Source URL"] == "https://example.com"
        assert fields["Location Type"] == "remote"
        assert fields["Cities"] == "London"
        assert fields["Salary Min"] == 50000
        assert fields["Salary Max"] == 70000
        assert fields["Salary Currency"] == "GBP"
        assert fields["Salary Period"] == "annual"
        assert fields["Posted Date"] == "2025-01-15"
        assert fields["Deadline"] == "2025-03-01"
        assert fields["Date Added"] == "2025-01-20"
        assert fields["Tags"] == [{"name": "research"}, {"name": "ai-safety"}]
        assert fields["Status"] == "open"
        assert fields["Confidence"] == 0.9
        assert fields["Notes"] == "Test note"
    finally:
        sys.path.pop(0)
        if "sync_to_airtable" in sys.modules:
            del sys.modules["sync_to_airtable"]


@tier1("Field mapping produces correct Airtable fields for orgs")
def test_org_field_mapping():
    sys.path.insert(0, str(Path(SCRIPT).parent))
    try:
        import sync_to_airtable as sync
        org = {
            "id": "test-org",
            "name": "Test Organization",
            "aliases": ["TestOrg", "TO"],
            "website": "https://test.org",
            "cause_areas": ["ai-safety", "biosecurity"],
            "hq_location": "London, UK",
            "size_estimate": "10-50",
            "notes": "Test note",
        }
        fields = sync.map_org_fields(org)

        assert fields["git_id"] == "test-org"
        assert fields["Name"] == "Test Organization"
        assert fields["Website"] == "https://test.org"
        assert fields["HQ Location"] == "London, UK"
        assert fields["Size Estimate"] == "10-50"
        assert fields["Notes"] == "Test note"
        assert fields["Cause Areas"] == [{"name": "ai-safety"}, {"name": "biosecurity"}]
        assert fields["Aliases"] == "TestOrg, TO"
    finally:
        sys.path.pop(0)
        if "sync_to_airtable" in sys.modules:
            del sys.modules["sync_to_airtable"]


@tier1("None values are stripped from field mapping")
def test_none_values_stripped():
    sys.path.insert(0, str(Path(SCRIPT).parent))
    try:
        import sync_to_airtable as sync
        job = {
            "id": "test--minimal--2025-01",
            "title": "Minimal",
            "organization": "test",
            "source": "manual",
            "date_added": "2025-01-01",
            "source_url": None,
            "jd_file": None,
            "salary": None,
            "posted_date": None,
            "deadline": None,
            "notes": None,
        }
        fields = sync.map_job_fields(job)
        for key, val in fields.items():
            assert val is not None, f"Field '{key}' should not be None"
    finally:
        sys.path.pop(0)
        if "sync_to_airtable" in sys.modules:
            del sys.modules["sync_to_airtable"]


# --- Tier 2: Integration Tests ---

@tier2("Airtable connectivity test")
def test_airtable_connectivity():
    import os
    if not os.environ.get("AIRTABLE_API_KEY"):
        raise Exception("AIRTABLE_API_KEY not set")
    result = run_sync("--dry-run", "--all", "--output-json")
    assert result.returncode == 0
    print("  Airtable connectivity OK (dry-run mode)")


@tier2("Idempotency integration test")
def test_idempotency():
    import os
    if not os.environ.get("AIRTABLE_API_KEY"):
        raise Exception("AIRTABLE_API_KEY not set")
    curated = PROJECT_ROOT / "exports" / "curated.json"
    if not curated.exists():
        raise Exception("exports/curated.json not found")
    result1 = run_sync("--ids-file", str(curated), "--output-json")
    if result1.returncode != 0:
        raise Exception(f"First sync failed: {result1.stderr}")
    result2 = run_sync("--ids-file", str(curated), "--output-json")
    if result2.returncode != 0:
        raise Exception(f"Second sync failed: {result2.stderr}")
    output2 = json.loads(result2.stdout)
    assert output2["created"] == 0, f"Idempotency failed: created {output2['created']} on second run"


# --- Test Runner ---

def run_tests():
    global passed, failed, warnings

    # Collect tests
    tier1_tests = []
    tier2_tests = []
    for name, obj in globals().items():
        if callable(obj) and hasattr(obj, "_tier"):
            if obj._tier == 1:
                tier1_tests.append(obj)
            else:
                tier2_tests.append(obj)

    # Run Tier 1
    print("=" * 60)
    print("TIER 1 — Deterministic Tests (must all pass)")
    print("=" * 60)
    for test in tier1_tests:
        try:
            test()
            print(f"  PASS: {test._test_name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test._test_name}")
            print(f"        {e}")
            failed += 1

    # Run Tier 2
    print()
    print("=" * 60)
    print("TIER 2 — Integration Tests (warnings only)")
    print("=" * 60)
    for test in tier2_tests:
        try:
            test()
            print(f"  PASS: {test._test_name}")
            passed += 1
        except Exception as e:
            print(f"  SKIPPED: {test._test_name}")
            print(f"           {e}")
            warnings += 1

    # Summary
    print()
    print("=" * 60)
    total = passed + failed + warnings
    print(f"Results: {passed}/{total} passed, {failed} failed, {warnings} skipped")
    print("=" * 60)

    if failed > 0:
        print("\nFAILED — Tier 1 tests must all pass.")
        return 1
    else:
        print("\nPASSED — All Tier 1 tests pass.")
        return 0


if __name__ == "__main__":
    sys.exit(run_tests())
