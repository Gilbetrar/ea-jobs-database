#!/usr/bin/env python3
"""
Data quality review script for EA Jobs Database.

Generates a quality report at exports/quality-report.md flagging:
- Low confidence records (confidence < 0.5)
- Missing critical fields (no title, no org, no source_url)
- Suspicious salaries (outliers: <$20k or >$500k annual equivalent)
- Duplicate jobs (same org + similar title + similar date)
- Dead JD links (jd_file set but file missing)
- Org records with no linked jobs
"""

import json
import glob
import os
import sys
from difflib import SequenceMatcher


def load_jobs():
    """Load all job records."""
    jobs = []
    for f in sorted(glob.glob("data/jobs/*.json")):
        with open(f) as fh:
            jobs.append(json.load(fh))
    return jobs


def load_orgs():
    """Load all org records."""
    orgs = []
    for f in sorted(glob.glob("data/orgs/*.json")):
        with open(f) as fh:
            orgs.append(json.load(fh))
    return orgs


def check_low_confidence(jobs):
    """Flag records with confidence < 0.5."""
    flagged = []
    for job in jobs:
        conf = job.get("confidence")
        if conf is not None and conf < 0.5:
            flagged.append(
                {
                    "id": job["id"],
                    "confidence": conf,
                    "title": job.get("title", ""),
                    "org": job.get("organization", ""),
                }
            )
    return flagged


def check_missing_fields(jobs):
    """Flag records missing critical fields."""
    flagged = []
    for job in jobs:
        missing = []
        if not job.get("title"):
            missing.append("title")
        if not job.get("organization"):
            missing.append("organization")
        if not job.get("source_url"):
            missing.append("source_url")
        if missing:
            flagged.append({"id": job["id"], "missing": missing})
    return flagged


def check_suspicious_salaries(jobs):
    """Flag salary outliers (<$20k or >$500k annual equivalent)."""
    flagged = []
    for job in jobs:
        salary = job.get("salary")
        if not salary:
            continue
        min_val = salary.get("min", 0) or 0
        max_val = salary.get("max", 0) or 0
        period = salary.get("period", "annual")
        currency = salary.get("currency", "USD")

        # Annualize monthly salaries
        annual_min = min_val * 12 if period == "monthly" else min_val
        annual_max = max_val * 12 if period == "monthly" else max_val

        reason = None
        if annual_min > 0 and annual_min < 20000:
            reason = f"Low min: {annual_min:,.0f} {currency}/yr"
        if annual_max > 500000:
            reason = f"High max: {annual_max:,.0f} {currency}/yr"
        if annual_min > 0 and annual_max > 0 and annual_max < annual_min:
            reason = f"Max < min: {annual_min:,.0f}-{annual_max:,.0f} {currency}/yr"

        if reason:
            flagged.append(
                {
                    "id": job["id"],
                    "reason": reason,
                    "raw_salary": salary,
                    "title": job.get("title", ""),
                }
            )
    return flagged


def check_duplicate_jobs(jobs):
    """Flag potential duplicate jobs (same org + similar title + close dates)."""
    flagged = []
    seen = set()

    # Group by org
    by_org = {}
    for job in jobs:
        org = job.get("organization", "")
        by_org.setdefault(org, []).append(job)

    for org, org_jobs in by_org.items():
        for i, j1 in enumerate(org_jobs):
            for j2 in org_jobs[i + 1 :]:
                pair_key = tuple(sorted([j1["id"], j2["id"]]))
                if pair_key in seen:
                    continue

                title_sim = SequenceMatcher(
                    None, j1.get("title", "").lower(), j2.get("title", "").lower()
                ).ratio()

                if title_sim < 0.8:
                    continue

                # Check date proximity (within 2 months)
                d1 = j1.get("posted_date") or j1.get("date_added", "")
                d2 = j2.get("posted_date") or j2.get("date_added", "")
                date_close = d1[:7] == d2[:7] if d1 and d2 else False

                if title_sim >= 0.9 or (title_sim >= 0.8 and date_close):
                    seen.add(pair_key)
                    flagged.append(
                        {
                            "id1": j1["id"],
                            "id2": j2["id"],
                            "title1": j1.get("title", ""),
                            "title2": j2.get("title", ""),
                            "similarity": round(title_sim, 3),
                        }
                    )
    return flagged


def check_dead_jd_links(jobs):
    """Flag jobs where jd_file is set but the file doesn't exist."""
    flagged = []
    for job in jobs:
        jd_file = job.get("jd_file")
        if jd_file and not os.path.isfile(jd_file):
            flagged.append({"id": job["id"], "jd_file": jd_file})
    return flagged


def check_orphan_orgs(jobs, orgs):
    """Flag org records with no linked jobs."""
    job_org_ids = {job.get("organization", "") for job in jobs}
    flagged = []
    for org in orgs:
        if org["id"] not in job_org_ids:
            flagged.append({"id": org["id"], "name": org.get("name", "")})
    return flagged


def generate_report(jobs, orgs):
    """Generate the full quality report."""
    low_conf = check_low_confidence(jobs)
    missing = check_missing_fields(jobs)
    salaries = check_suspicious_salaries(jobs)
    duplicates = check_duplicate_jobs(jobs)
    dead_links = check_dead_jd_links(jobs)
    orphan_orgs = check_orphan_orgs(jobs, orgs)

    lines = []
    lines.append("# Data Quality Report")
    lines.append("")
    lines.append(f"**Generated:** {__import__('datetime').date.today()}")
    lines.append(f"**Total jobs:** {len(jobs)}")
    lines.append(f"**Total orgs:** {len(orgs)}")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Category | Count |")
    lines.append(f"|----------|-------|")
    lines.append(f"| Low confidence (<0.5) | {len(low_conf)} |")
    lines.append(f"| Missing fields | {len(missing)} |")
    lines.append(f"| Suspicious salary | {len(salaries)} |")
    lines.append(f"| Duplicate jobs | {len(duplicates)} |")
    lines.append(f"| Dead JD link | {len(dead_links)} |")
    lines.append(f"| Orphan orgs (no jobs) | {len(orphan_orgs)} |")
    lines.append("")

    # Low confidence
    lines.append("## Low Confidence Records")
    lines.append("")
    if low_conf:
        lines.append("| Job ID | Confidence | Title | Org |")
        lines.append("|--------|------------|-------|-----|")
        for r in low_conf:
            lines.append(
                f"| `{r['id']}` | {r['confidence']:.2f} | {r['title']} | {r['org']} |"
            )
    else:
        lines.append("No low confidence records found.")
    lines.append("")

    # Missing fields
    lines.append("## Missing Fields")
    lines.append("")
    if missing:
        lines.append("| Job ID | Missing |")
        lines.append("|--------|---------|")
        for r in missing:
            lines.append(f"| `{r['id']}` | {', '.join(r['missing'])} |")
    else:
        lines.append("No records with missing critical fields.")
    lines.append("")

    # Suspicious salary
    lines.append("## Suspicious Salary")
    lines.append("")
    if salaries:
        lines.append("| Job ID | Issue | Title |")
        lines.append("|--------|-------|-------|")
        for r in salaries:
            lines.append(f"| `{r['id']}` | {r['reason']} | {r['title']} |")
    else:
        lines.append("No suspicious salaries found.")
    lines.append("")

    # Duplicates
    lines.append("## Duplicate Jobs")
    lines.append("")
    if duplicates:
        lines.append("| Job 1 | Job 2 | Similarity |")
        lines.append("|-------|-------|------------|")
        for r in duplicates:
            lines.append(
                f"| `{r['id1']}` | `{r['id2']}` | {r['similarity']:.1%} |"
            )
    else:
        lines.append("No duplicate jobs detected.")
    lines.append("")

    # Dead links
    lines.append("## Dead Link Check (JD Files)")
    lines.append("")
    if dead_links:
        lines.append("| Job ID | Missing File |")
        lines.append("|--------|-------------|")
        for r in dead_links:
            lines.append(f"| `{r['id']}` | `{r['jd_file']}` |")
    else:
        lines.append("No dead link issues found.")
    lines.append("")

    # Orphan orgs
    lines.append("## Orphan Orgs (No Linked Jobs)")
    lines.append("")
    if orphan_orgs:
        lines.append("| Org ID | Name |")
        lines.append("|--------|------|")
        for r in orphan_orgs:
            lines.append(f"| `{r['id']}` | {r['name']} |")
    else:
        lines.append("No orphan orgs found.")
    lines.append("")

    return "\n".join(lines)


def main():
    print("Loading data...")
    jobs = load_jobs()
    orgs = load_orgs()
    print(f"Loaded {len(jobs)} jobs, {len(orgs)} orgs")

    print("Generating quality report...")
    report = generate_report(jobs, orgs)

    os.makedirs("exports", exist_ok=True)
    output_path = "exports/quality-report.md"
    with open(output_path, "w") as f:
        f.write(report)

    print(f"Report written to {output_path}")

    # Print summary to stdout
    low_conf = check_low_confidence(jobs)
    missing = check_missing_fields(jobs)
    salaries = check_suspicious_salaries(jobs)
    duplicates = check_duplicate_jobs(jobs)
    dead_links = check_dead_jd_links(jobs)
    orphan_orgs = check_orphan_orgs(jobs, orgs)

    total_issues = (
        len(low_conf)
        + len(missing)
        + len(salaries)
        + len(duplicates)
        + len(dead_links)
        + len(orphan_orgs)
    )
    print(f"\nTotal issues found: {total_issues}")
    print(f"  Low confidence: {len(low_conf)}")
    print(f"  Missing fields: {len(missing)}")
    print(f"  Suspicious salaries: {len(salaries)}")
    print(f"  Duplicate jobs: {len(duplicates)}")
    print(f"  Dead JD links: {len(dead_links)}")
    print(f"  Orphan orgs: {len(orphan_orgs)}")


if __name__ == "__main__":
    main()
