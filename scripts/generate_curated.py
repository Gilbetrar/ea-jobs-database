#!/usr/bin/env python3
"""
Curated subset generator for EA Jobs Database.

Generates exports/curated.json — the list of job IDs to sync to Airtable.

Selection criteria (configurable via CLI):
- Confidence >= threshold (default 0.7)
- Has at least: title, organization, source_url
- Prefers: has salary data, has JD archived, posted within last 6 months

Usage:
    python3 scripts/generate_curated.py
    python3 scripts/generate_curated.py --min-confidence 0.8 --max-age-months 3
    python3 scripts/generate_curated.py --target-count 250
"""

import argparse
import json
import glob
import os
import sys
from datetime import date, timedelta


def load_jobs():
    """Load all job records."""
    jobs = []
    for f in sorted(glob.glob("data/jobs/*.json")):
        with open(f) as fh:
            jobs.append(json.load(fh))
    return jobs


def score_job(job, today, max_age_days):
    """Score a job for curation priority. Higher = better."""
    score = 0

    # Base: confidence
    conf = job.get("confidence", 0)
    score += conf * 10  # 0-10 points

    # Has salary data
    if job.get("salary"):
        score += 3

    # Has JD archived
    jd_file = job.get("jd_file")
    if jd_file and os.path.isfile(jd_file):
        score += 2

    # Recency bonus
    posted = job.get("posted_date") or job.get("date_added", "")
    if posted:
        try:
            posted_date = date.fromisoformat(posted)
            age_days = (today - posted_date).days
            if age_days <= max_age_days:
                # Linear bonus: newer = higher score (0-5 points)
                score += 5 * (1 - age_days / max_age_days)
        except ValueError:
            pass

    # Has location info
    if job.get("location"):
        score += 1

    # Has tags
    if job.get("tags"):
        score += 1

    return score


def generate_curated(jobs, min_confidence=0.7, max_age_months=6, target_count=300):
    """Generate curated subset of jobs."""
    today = date.today()
    max_age_days = max_age_months * 30

    # Phase 1: Filter hard requirements
    eligible = []
    excluded = {"low_confidence": 0, "missing_fields": 0}

    for job in jobs:
        # Hard requirement: confidence threshold
        conf = job.get("confidence", 0)
        if conf < min_confidence:
            excluded["low_confidence"] += 1
            continue

        # Hard requirement: critical fields
        if not job.get("title") or not job.get("organization") or not job.get("source_url"):
            excluded["missing_fields"] += 1
            continue

        eligible.append(job)

    # Phase 2: Score and rank
    scored = []
    for job in eligible:
        s = score_job(job, today, max_age_days)
        scored.append((s, job))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Phase 3: Select top N
    selected = scored[:target_count]
    curated_ids = [job["id"] for _, job in selected]

    # Generate summary
    summary = {
        "total_jobs": len(jobs),
        "eligible": len(eligible),
        "selected": len(curated_ids),
        "excluded": excluded,
        "criteria": {
            "min_confidence": min_confidence,
            "max_age_months": max_age_months,
            "target_count": target_count,
        },
    }

    # Stats on selected
    has_salary = sum(1 for _, j in selected if j.get("salary"))
    has_jd = sum(1 for _, j in selected if j.get("jd_file") and os.path.isfile(j.get("jd_file", "")))
    summary["selected_stats"] = {
        "has_salary": has_salary,
        "has_jd": has_jd,
    }

    return curated_ids, summary


def main():
    parser = argparse.ArgumentParser(description="Generate curated job subset for Airtable")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.7,
        help="Minimum confidence threshold (default: 0.7)",
    )
    parser.add_argument(
        "--max-age-months",
        type=int,
        default=6,
        help="Maximum age in months for recency bonus (default: 6)",
    )
    parser.add_argument(
        "--target-count",
        type=int,
        default=300,
        help="Target number of curated records (default: 300)",
    )
    args = parser.parse_args()

    print("Loading jobs...", file=sys.stderr)
    jobs = load_jobs()
    print(f"Loaded {len(jobs)} jobs", file=sys.stderr)

    curated_ids, summary = generate_curated(
        jobs,
        min_confidence=args.min_confidence,
        max_age_months=args.max_age_months,
        target_count=args.target_count,
    )

    os.makedirs("exports", exist_ok=True)

    # Write curated IDs
    with open("exports/curated.json", "w") as f:
        json.dump(curated_ids, f, indent=2)
        f.write("\n")

    # Write summary
    with open("exports/curated-summary.json", "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    print(f"\nCuration summary:", file=sys.stderr)
    print(f"  Total jobs: {summary['total_jobs']}", file=sys.stderr)
    print(f"  Eligible (passed filters): {summary['eligible']}", file=sys.stderr)
    print(f"  Selected (curated): {summary['selected']}", file=sys.stderr)
    print(f"  Excluded - low confidence: {summary['excluded']['low_confidence']}", file=sys.stderr)
    print(f"  Excluded - missing fields: {summary['excluded']['missing_fields']}", file=sys.stderr)
    print(f"  With salary: {summary['selected_stats']['has_salary']}", file=sys.stderr)
    print(f"  With JD: {summary['selected_stats']['has_jd']}", file=sys.stderr)
    print(f"\nWritten to exports/curated.json and exports/curated-summary.json", file=sys.stderr)


if __name__ == "__main__":
    main()
