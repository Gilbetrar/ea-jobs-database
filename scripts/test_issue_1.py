#!/usr/bin/env python3
"""Validation script for Issue #1: Repo Setup + Schema Design.

Verifies all deliverables are present and correct.
Exit code 0 = all checks pass, non-zero = failure.
"""

import glob
import json
import os
import sys

# Ensure we run from the repo root
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []
warnings = []


def check(description, condition, msg=""):
    if condition:
        print(f"  PASS: {description}")
    else:
        detail = f"{description}: {msg}" if msg else description
        print(f"  FAIL: {detail}")
        failures.append(detail)


def warn(description, condition, msg=""):
    if condition:
        print(f"  PASS: {description}")
    else:
        detail = f"{description}: {msg}" if msg else description
        print(f"  WARN: {detail}")
        warnings.append(detail)


# ---------------------------------------------------------------------------
# Tier 1: Deterministic checks (must all pass)
# ---------------------------------------------------------------------------
print("\n=== Tier 1: Deterministic Checks ===\n")

# 1. Schema meta-validation
print("--- Schema Meta-Validation ---")
try:
    import jsonschema
except ImportError:
    print("FATAL: jsonschema not installed. Run: pip install jsonschema")
    sys.exit(1)

try:
    with open("schemas/job.schema.json") as f:
        job_schema = json.load(f)
    jsonschema.Draft7Validator.check_schema(job_schema)
    check("Job schema is valid Draft-07", True)
except Exception as e:
    check("Job schema is valid Draft-07", False, str(e))

try:
    with open("schemas/org.schema.json") as f:
        org_schema = json.load(f)
    jsonschema.Draft7Validator.check_schema(org_schema)
    check("Org schema is valid Draft-07", True)
except Exception as e:
    check("Org schema is valid Draft-07", False, str(e))

# 2. Sample files validate against their own schemas
print("\n--- Sample File Validation ---")
job_files = [f for f in glob.glob("data/jobs/*.json") if not f.endswith(".gitkeep")]
org_files = [f for f in glob.glob("data/orgs/*.json") if not f.endswith(".gitkeep")]

check("At least one sample job file exists", len(job_files) > 0, "No JSON files in data/jobs/")
check("At least one sample org file exists", len(org_files) > 0, "No JSON files in data/orgs/")

for sample in job_files:
    try:
        with open(sample) as f:
            data = json.load(f)
        jsonschema.validate(data, job_schema)
        check(f"Job file validates: {sample}", True)
    except Exception as e:
        check(f"Job file validates: {sample}", False, str(e))

for sample in org_files:
    try:
        with open(sample) as f:
            data = json.load(f)
        jsonschema.validate(data, org_schema)
        check(f"Org file validates: {sample}", True)
    except Exception as e:
        check(f"Org file validates: {sample}", False, str(e))

# 3. Directory structure — .gitkeep in each directory
print("\n--- Directory Structure ---")
for d in ["data/jobs", "data/orgs", "data/jds", "exports"]:
    gitkeep = os.path.join(d, ".gitkeep")
    check(f".gitkeep exists in {d}", os.path.isfile(gitkeep), f"Missing {gitkeep}")

# 4. README.md contains required sections
print("\n--- README.md Sections ---")
try:
    with open("README.md") as f:
        readme = f.read()
    for section in ["Overview", "Architecture", "Data Sources", "Contribute"]:
        check(
            f"README contains '{section}'",
            section.lower() in readme.lower(),
            f"Missing section: {section}",
        )
except FileNotFoundError:
    check("README.md exists", False, "File not found")

# 5. AGENTS.md contains required sections
print("\n--- AGENTS.md Sections ---")
try:
    with open("AGENTS.md") as f:
        agents = f.read()
    for section in ["Workflow", "Scripts", "Data", "Convention"]:
        check(
            f"AGENTS.md contains '{section}'",
            section.lower() in agents.lower(),
            f"Missing section: {section}",
        )
except FileNotFoundError:
    check("AGENTS.md exists", False, "File not found")

# 6. Schema files exist
print("\n--- Schema Files ---")
check("schemas/job.schema.json exists", os.path.isfile("schemas/job.schema.json"))
check("schemas/org.schema.json exists", os.path.isfile("schemas/org.schema.json"))

# ---------------------------------------------------------------------------
# Tier 2: Integration checks (warnings only)
# ---------------------------------------------------------------------------
print("\n=== Tier 2: Integration Checks ===\n")

print("--- Airtable ---")
warn(
    "Airtable verification",
    False,
    "Skipped (Airtable MCP not available in this environment)",
)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n=== Summary ===\n")
print(f"  Failures: {len(failures)}")
print(f"  Warnings: {len(warnings)}")

if failures:
    print("\nFailed checks:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("\nAll Tier 1 checks passed!")
    sys.exit(0)
