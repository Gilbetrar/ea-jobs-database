#!/usr/bin/env python3
"""
Test script for Issue #6: Data Quality Review + Org Deduplication.

Phased verification:
- Phase 1: Automated pre-merge checks (quality report, proposed merges)
- Phase 2: Human review required (printed as SKIPPED)
- Phase 3: Post-merge checks (run only after human approval and --apply)

Usage:
    python3 scripts/test_issue_6.py              # Runs Phase 1 only
    python3 scripts/test_issue_6.py --post-merge  # Runs Phase 3 (after merge applied)
"""

import json
import glob
import os
import sys

PASS = 0
FAIL = 0
WARN = 0


def check(label, condition, msg=""):
    global PASS, FAIL
    if condition:
        print(f"  PASS: {label}")
        PASS += 1
    else:
        print(f"  FAIL: {label} — {msg}")
        FAIL += 1


def warn(label, condition, msg=""):
    global WARN
    if condition:
        print(f"  PASS: {label}")
    else:
        print(f"  WARNING: {label} — {msg}")
        WARN += 1


def phase1():
    """Phase 1 — Automated Pre-Merge (Tier 1, MUST all pass)."""
    print("\n=== Phase 1: Pre-Merge Checks ===\n")

    # 1. Quality report exists and contains required sections
    report_exists = os.path.isfile("exports/quality-report.md")
    check("Quality report exists", report_exists)

    if report_exists:
        report = open("exports/quality-report.md").read().lower()
        for section in [
            "low confidence",
            "missing field",
            "salary",
            "duplicate",
            "dead link",
        ]:
            check(
                f"Report has '{section}' section",
                section in report,
                f"missing section: {section}",
            )

    # 2. Proposed merges file exists and is valid JSON with confidence scores
    merges_exists = os.path.isfile("exports/proposed-merges.json")
    check("Proposed merges file exists", merges_exists)

    if merges_exists:
        with open("exports/proposed-merges.json") as f:
            merges = json.load(f)
        check("Proposed merges is a list", isinstance(merges, list))

        for i, merge in enumerate(merges):
            check(
                f"Merge {i} has confidence",
                "confidence" in merge,
                f"missing confidence: {merge}",
            )
            if "confidence" in merge:
                check(
                    f"Merge {i} confidence is numeric",
                    isinstance(merge["confidence"], (int, float)),
                )
                check(
                    f"Merge {i} confidence in range",
                    0 <= merge["confidence"] <= 1,
                    f"value: {merge.get('confidence')}",
                )

    # 3. Fixture test — verify merge detection works on known patterns
    # Test with orgs that have high name similarity (fuzzy match target)
    print("\n  --- Fixture: merge detection ---")
    try:
        sys.path.insert(0, "scripts")
        from merge_orgs import find_proposed_merges

        # Create synthetic test data with similar names (should trigger fuzzy match)
        test_orgs = {
            "test-open-philanthropy": {
                "id": "test-open-philanthropy",
                "name": "Open Philanthropy",
                "aliases": [],
            },
            "test-open-philanthropy-project": {
                "id": "test-open-philanthropy-project",
                "name": "Open Philanthropy Project",
                "aliases": [],
            },
        }
        proposals = find_proposed_merges(test_orgs, threshold=0.80)
        check(
            "Fixture: fuzzy merge detection finds similar org names",
            len(proposals) > 0,
            "no proposals generated for 'Open Philanthropy' vs 'Open Philanthropy Project'",
        )
    except Exception as e:
        check("Fixture: merge detection", False, str(e))

    # 4. Review script exists and is runnable
    check(
        "Review script exists",
        os.path.isfile("scripts/review_data.py"),
    )
    check(
        "Merge script exists",
        os.path.isfile("scripts/merge_orgs.py"),
    )
    check(
        "Curated generator exists",
        os.path.isfile("scripts/generate_curated.py"),
    )


def phase2():
    """Phase 2 — Human review checkpoint."""
    print("\n=== Phase 2: Human Review ===\n")
    print("  PHASE 2 SKIPPED (requires human review of proposed-merges.json)")
    print("  Review exports/proposed-merges.json and approve before running Phase 3.")


def phase3():
    """Phase 3 — Automated Post-Merge (run only after Phase 2 approval)."""
    print("\n=== Phase 3: Post-Merge Checks ===\n")

    # 4. After --apply: no fuzzy-similar org names remain (similarity > 0.85)
    try:
        from rapidfuzz import fuzz

        org_files = glob.glob("data/orgs/*.json")
        org_names = []
        for f in org_files:
            with open(f) as fh:
                org_names.append(json.load(fh)["name"])

        similar_pairs = []
        for i, name1 in enumerate(org_names):
            for name2 in org_names[i + 1 :]:
                sim = fuzz.ratio(name1.lower(), name2.lower()) / 100
                if sim > 0.85:
                    similar_pairs.append((name1, name2, sim))

        check(
            "No fuzzy-similar org names remain (>0.85)",
            len(similar_pairs) == 0,
            f"found {len(similar_pairs)} similar pairs: "
            + "; ".join(f"'{a}' vs '{b}' ({s:.2f})" for a, b, s in similar_pairs[:3]),
        )
    except ImportError:
        check("rapidfuzz available", False, "install with: pip3 install rapidfuzz")

    # 5. Curated subset exists and meets count threshold
    curated_exists = os.path.isfile("exports/curated.json")
    check("Curated subset exists", curated_exists)

    if curated_exists:
        with open("exports/curated.json") as f:
            curated = json.load(f)
        check(
            f"Curated count in range (200-400): got {len(curated)}",
            200 <= len(curated) <= 400,
            f"count {len(curated)} outside 200-400 range",
        )

        # 6. All curated IDs reference existing job files
        missing_jobs = []
        for job_id in curated:
            job_path = f"data/jobs/{job_id}.json"
            if not os.path.isfile(job_path):
                missing_jobs.append(job_id)
        check(
            "All curated IDs have job files",
            len(missing_jobs) == 0,
            f"{len(missing_jobs)} missing: {missing_jobs[:3]}",
        )

    # Tier 2: Integration spot-check
    print("\n  --- Tier 2: Integration (warnings only) ---")
    if curated_exists:
        for job_id in curated[:10]:
            try:
                with open(f"data/jobs/{job_id}.json") as f:
                    job = json.load(f)
                warn(
                    f"Curated {job_id} confidence >= 0.7",
                    job.get("confidence", 0) >= 0.7,
                    f"confidence: {job.get('confidence')}",
                )
                warn(
                    f"Curated {job_id} has title",
                    bool(job.get("title")),
                )
                warn(
                    f"Curated {job_id} has org",
                    bool(job.get("organization")),
                )
            except Exception as e:
                warn(f"Curated {job_id} readable", False, str(e))


def main():
    post_merge = "--post-merge" in sys.argv

    phase1()
    phase2()

    if post_merge:
        phase3()
    else:
        print("\n  Phase 3 skipped (run with --post-merge after applying merges)")

    print(f"\n{'='*40}")
    print(f"Results: {PASS} passed, {FAIL} failed, {WARN} warnings")

    if FAIL > 0:
        print("OVERALL: FAIL")
        sys.exit(1)
    else:
        print("OVERALL: PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
