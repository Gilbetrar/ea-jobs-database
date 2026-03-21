#!/usr/bin/env python3
"""Bulk upload all jobs to Airtable with denormalized org info and JD content.

Usage:
  AIRTABLE_PAT=patXXX python scripts/bulk_upload.py              # Create all records
  AIRTABLE_PAT=patXXX python scripts/bulk_upload.py --dry-run    # Preview creation
  AIRTABLE_PAT=patXXX python scripts/bulk_upload.py --update-only          # Patch JDs on existing records
  AIRTABLE_PAT=patXXX python scripts/bulk_upload.py --update-only --dry-run  # Preview JD patches
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
JOBS_DIR = PROJECT_ROOT / "data" / "jobs"
ORGS_DIR = PROJECT_ROOT / "data" / "orgs"
JDS_DIR = PROJECT_ROOT / "data" / "jds"

BASE_ID = "appqj3tw0d9apVbA8"
TABLE_NAME = "Jobs"
BATCH_SIZE = 10
RATE_LIMIT_DELAY = 0.25  # seconds between API calls


def log(msg):
    print(msg, file=sys.stderr)


def load_orgs_index():
    """Load all orgs into a dict keyed by org ID."""
    index = {}
    for f in ORGS_DIR.glob("*.json"):
        org = json.load(open(f))
        index[org["id"]] = org
    log(f"Loaded {len(index)} orgs")
    return index


def load_jd(job_id):
    """Load JD markdown content for a job ID."""
    jd_path = JDS_DIR / f"{job_id}.md"
    if jd_path.exists():
        return jd_path.read_text(encoding="utf-8")
    return None


def map_record(job, orgs_index):
    """Map a job JSON + org + JD to Airtable fields."""
    fields = {
        "git_id": job["id"],
        "Title": job.get("title", ""),
        "Organization": job.get("organization", ""),
        "Source": job.get("source"),
        "Status": job.get("status", "unknown"),
    }

    if job.get("source_url"):
        fields["Source URL"] = job["source_url"]
    if job.get("confidence") is not None:
        fields["Confidence"] = job["confidence"]
    if job.get("notes"):
        fields["Notes"] = job["notes"]
    if job.get("date_added"):
        fields["Date Added"] = job["date_added"]
    if job.get("posted_date"):
        fields["Posted Date"] = job["posted_date"]
    if job.get("deadline"):
        fields["Deadline"] = job["deadline"]

    # Tags
    if job.get("tags"):
        fields["Tags"] = job["tags"]

    # Location
    loc = job.get("location")
    if loc:
        if loc.get("type"):
            fields["Location Type"] = loc["type"]
        cities = loc.get("cities", [])
        if cities:
            fields["Cities"] = ", ".join(cities)

    # Salary
    sal = job.get("salary")
    if sal:
        if sal.get("min") is not None:
            fields["Salary Min"] = sal["min"]
        if sal.get("max") is not None:
            fields["Salary Max"] = sal["max"]
        if sal.get("currency"):
            fields["Salary Currency"] = sal["currency"]
        if sal.get("period"):
            fields["Salary Period"] = sal["period"]

    # Denormalized org info
    org_id = job.get("organization", "")
    org = orgs_index.get(org_id, {})
    if org.get("name"):
        fields["Organization"] = org["name"]  # Use full name instead of slug
    if org.get("website"):
        fields["Org Website"] = org["website"]
    if org.get("hq_location"):
        fields["Org HQ"] = org["hq_location"]
    if org.get("cause_areas"):
        fields["Org Cause Areas"] = ", ".join(org["cause_areas"])

    # JD content
    jd_content = load_jd(job["id"])
    if jd_content:
        fields["Job Description"] = jd_content

    # Strip None values
    return {k: v for k, v in fields.items() if v is not None}


def airtable_request(method, url, data, api_key):
    """Make an authenticated Airtable API request."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"Airtable API error {e.code}: {error_body}") from e


def fetch_all_records(api_key):
    """Fetch all records from Airtable, returning {git_id: record_id} mapping."""
    base_url = f"https://api.airtable.com/v0/{BASE_ID}/{urllib.request.quote(TABLE_NAME)}"
    mapping = {}
    offset = None

    while True:
        params = "fields%5B%5D=git_id"
        if offset:
            params += f"&offset={offset}"
        url = f"{base_url}?{params}"

        result = airtable_request("GET", url, None, api_key)
        for record in result.get("records", []):
            git_id = record.get("fields", {}).get("git_id")
            if git_id:
                mapping[git_id] = record["id"]

        offset = result.get("offset")
        if not offset:
            break
        time.sleep(RATE_LIMIT_DELAY)

    log(f"Fetched {len(mapping)} existing records from Airtable")
    return mapping


def batch_update(updates, api_key, dry_run=False):
    """Update records in batches of 10. Each update is (record_id, fields_dict)."""
    url = f"https://api.airtable.com/v0/{BASE_ID}/{urllib.request.quote(TABLE_NAME)}"
    total = len(updates)
    updated = 0
    errors = 0

    for i in range(0, total, BATCH_SIZE):
        batch = updates[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

        if dry_run:
            log(f"  [DRY RUN] Batch {batch_num}/{total_batches}: {len(batch)} records")
            updated += len(batch)
            continue

        data = {
            "records": [
                {"id": record_id, "fields": fields}
                for record_id, fields in batch
            ],
            "typecast": True,
        }

        try:
            result = airtable_request("PATCH", url, data, api_key)
            n = len(result.get("records", []))
            updated += n
            log(f"  Batch {batch_num}/{total_batches}: updated {n} records ({updated}/{total})")
        except RuntimeError as e:
            if "401" in str(e) or "403" in str(e):
                log(f"  AUTH ERROR: {e}")
                log("  Aborting — check your AIRTABLE_PAT.")
                return updated, total - updated
            errors += len(batch)
            log(f"  Batch {batch_num}/{total_batches}: ERROR - {e}")

        time.sleep(RATE_LIMIT_DELAY)

    return updated, errors


def batch_create(records_fields, api_key, dry_run=False):
    """Create records in batches of 10."""
    url = f"https://api.airtable.com/v0/{BASE_ID}/{urllib.request.quote(TABLE_NAME)}"
    total = len(records_fields)
    created = 0
    errors = 0

    for i in range(0, total, BATCH_SIZE):
        batch = records_fields[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

        if dry_run:
            log(f"  [DRY RUN] Batch {batch_num}/{total_batches}: {len(batch)} records")
            created += len(batch)
            continue

        data = {
            "records": [{"fields": f} for f in batch],
            "typecast": True,
        }

        try:
            result = airtable_request("POST", url, data, api_key)
            n = len(result.get("records", []))
            created += n
            log(f"  Batch {batch_num}/{total_batches}: created {n} records ({created}/{total})")
        except RuntimeError as e:
            if "401" in str(e) or "403" in str(e):
                log(f"  AUTH ERROR: {e}")
                log("  Aborting — check your AIRTABLE_PAT.")
                return created, total - created
            errors += len(batch)
            log(f"  Batch {batch_num}/{total_batches}: ERROR - {e}")

        time.sleep(RATE_LIMIT_DELAY)

    return created, errors


def run_update_only(api_key, dry_run=False):
    """Patch Job Description field on existing Airtable records."""
    log("Mode: --update-only (patching Job Description on existing records)")

    # Step 1: Fetch existing record IDs from Airtable
    if not dry_run:
        log("Fetching existing records from Airtable...")
        record_map = fetch_all_records(api_key)
    else:
        # In dry-run without API key, build a fake map from job files
        log("Dry run: scanning local job files...")
        record_map = {}
        for f in sorted(JOBS_DIR.glob("*.json")):
            job = json.load(open(f))
            record_map[job["id"]] = f"rec_DRYRUN_{job['id'][:20]}"
        log(f"  (simulated {len(record_map)} records)")

    # Step 2: Build update list — only records that have JD files
    updates = []
    skipped_no_jd = 0
    skipped_not_in_airtable = 0
    skipped_oversized = []

    jd_files = sorted(JDS_DIR.glob("*.md"))
    log(f"Found {len(jd_files)} JD files locally")

    for jd_path in jd_files:
        job_id = jd_path.stem  # filename without .md
        jd_content = jd_path.read_text(encoding="utf-8")

        if not jd_content.strip():
            skipped_no_jd += 1
            continue

        record_id = record_map.get(job_id)
        if not record_id:
            skipped_not_in_airtable += 1
            continue

        # Airtable Long Text field limit is 100,000 characters — skip oversized
        if len(jd_content) > 100000:
            skipped_oversized.append((job_id, len(jd_content)))
            continue

        updates.append((record_id, {"Job Description": jd_content}))

    log(f"Prepared {len(updates)} JD updates")
    log(f"  Skipped: {skipped_no_jd} empty JDs, {skipped_not_in_airtable} not in Airtable, {len(skipped_oversized)} oversized (>100K chars)")
    for job_id, size in skipped_oversized:
        log(f"    Oversized: {job_id} ({size:,} chars)")

    if dry_run:
        log("\n--- DRY RUN ---")

    # Step 3: Batch update
    updated, errors = batch_update(updates, api_key, dry_run=dry_run)

    log(f"\nDone: {updated} updated, {errors} errors out of {len(updates)} total")
    return errors


def main():
    dry_run = "--dry-run" in sys.argv
    update_only = "--update-only" in sys.argv

    api_key = os.environ.get("AIRTABLE_PAT")
    if not api_key and not dry_run:
        log("Error: Set AIRTABLE_PAT environment variable with your Personal Access Token.")
        log("  Create one at: https://airtable.com/create/tokens")
        log("  Required scopes: data.records:write, data.records:read")
        log("  Or use --dry-run to preview without uploading.")
        sys.exit(1)

    if update_only:
        errors = run_update_only(api_key, dry_run=dry_run)
        if errors > 0:
            sys.exit(1)
        return

    # Load org index
    orgs_index = load_orgs_index()

    # Load and map all jobs
    log("Loading jobs...")
    job_files = sorted(JOBS_DIR.glob("*.json"))
    log(f"Found {len(job_files)} job files")

    records = []
    for f in job_files:
        job = json.load(open(f))
        fields = map_record(job, orgs_index)
        records.append(fields)

    log(f"Mapped {len(records)} records for upload")

    if dry_run:
        log("\n--- DRY RUN ---")

    # Upload
    created, errors = batch_create(records, api_key, dry_run=dry_run)

    log(f"\nDone: {created} created, {errors} errors out of {len(records)} total")

    if errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
