#!/usr/bin/env python3
"""Sync job and org records from the git repo to Airtable.

Airtable is the curated browsable view — not the primary store.
The git repo holds everything; Airtable holds a selective subset.

Environment variables required:
  AIRTABLE_API_KEY   - Airtable personal access token
  AIRTABLE_BASE_ID   - Airtable base ID (e.g. appXXXXXXXXXXXXXX)

Optional environment variables:
  AIRTABLE_JOBS_TABLE_ID  - Jobs table ID (default: "Jobs")
  AIRTABLE_ORGS_TABLE_ID  - Orgs table ID (default: "Organizations")

Usage:
  python scripts/sync_to_airtable.py --dry-run --all
  python scripts/sync_to_airtable.py --ids job-id-1 job-id-2
  python scripts/sync_to_airtable.py --ids-file exports/curated.json
  python scripts/sync_to_airtable.py --all --output-json
  python scripts/sync_to_airtable.py --filter "status=open" --dry-run
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Resolve project root relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
JOBS_DIR = PROJECT_ROOT / "data" / "jobs"
ORGS_DIR = PROJECT_ROOT / "data" / "orgs"

# Airtable free tier limit
RECORD_LIMIT = 1000
WARNING_THRESHOLD = 800   # 80%
ERROR_THRESHOLD = 950     # 95%

# Rate limiting
AIRTABLE_RATE_LIMIT_DELAY = 0.25  # seconds between API calls


def log(msg, file=sys.stderr):
    """Print log messages to stderr so --output-json stdout stays clean."""
    print(msg, file=file)


# --- Airtable API Client ---

class AirtableClient:
    """Minimal Airtable REST API client using stdlib only."""

    def __init__(self, api_key, base_id, jobs_table, orgs_table):
        self.api_key = api_key
        self.base_id = base_id
        self.jobs_table = jobs_table
        self.orgs_table = orgs_table
        self.base_url = f"https://api.airtable.com/v0/{base_id}"

    def _request(self, method, url, data=None):
        """Make an authenticated request to Airtable API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise RuntimeError(
                f"Airtable API error {e.code}: {error_body}"
            ) from e

    def list_records(self, table, fields=None):
        """List all records in a table, handling pagination."""
        records = []
        params = []
        if fields:
            for f in fields:
                params.append(f"fields%5B%5D={urllib.request.quote(f)}")
        offset = None
        while True:
            url = f"{self.base_url}/{urllib.request.quote(table)}"
            query_parts = list(params)
            if offset:
                query_parts.append(f"offset={offset}")
            if query_parts:
                url += "?" + "&".join(query_parts)
            result = self._request("GET", url)
            records.extend(result.get("records", []))
            offset = result.get("offset")
            if not offset:
                break
            time.sleep(AIRTABLE_RATE_LIMIT_DELAY)
        return records

    def create_record(self, table, fields):
        """Create a single record."""
        url = f"{self.base_url}/{urllib.request.quote(table)}"
        data = {"fields": fields}
        result = self._request("POST", url, data)
        time.sleep(AIRTABLE_RATE_LIMIT_DELAY)
        return result

    def update_record(self, table, record_id, fields):
        """Update a single record by Airtable record ID."""
        url = f"{self.base_url}/{urllib.request.quote(table)}/{record_id}"
        data = {"fields": fields}
        result = self._request("PATCH", url, data)
        time.sleep(AIRTABLE_RATE_LIMIT_DELAY)
        return result

    def get_record_count(self):
        """Get total record count across Jobs and Orgs tables."""
        jobs = self.list_records(self.jobs_table, fields=["git_id"])
        orgs = self.list_records(self.orgs_table, fields=["git_id"])
        return len(jobs) + len(orgs)

    def get_existing_records(self, table):
        """Get existing records indexed by git_id for dedup."""
        records = self.list_records(table, fields=["git_id"])
        index = {}
        for rec in records:
            git_id = rec.get("fields", {}).get("git_id")
            if git_id:
                index[git_id] = rec["id"]
        return index


class DryRunClient:
    """Mock client that logs what would happen without touching Airtable."""

    def __init__(self):
        self._jobs_index = {}
        self._orgs_index = {}

    def get_record_count(self):
        return 0

    def get_existing_records(self, table):
        return {}

    def create_record(self, table, fields):
        log(f"  [DRY RUN] Would CREATE in {table}: {fields.get('git_id', '?')}")
        return {"id": "dry_run_id", "fields": fields}

    def update_record(self, table, record_id, fields):
        log(f"  [DRY RUN] Would UPDATE in {table}: {fields.get('git_id', '?')}")
        return {"id": record_id, "fields": fields}


# --- Field Mapping ---

def map_job_fields(job_data):
    """Map a job JSON record to Airtable field names/types."""
    fields = {
        "git_id": job_data["id"],
        "Title": job_data.get("title", ""),
        "Organization": job_data.get("organization", ""),
        "Source": job_data.get("source", ""),
        "Status": job_data.get("status", "unknown"),
        "Confidence": job_data.get("confidence"),
        "Notes": job_data.get("notes"),
        "Date Added": job_data.get("date_added"),
    }

    # URL fields
    if job_data.get("source_url"):
        fields["Source URL"] = job_data["source_url"]

    # Date fields
    if job_data.get("posted_date"):
        fields["Posted Date"] = job_data["posted_date"]
    if job_data.get("deadline"):
        fields["Deadline"] = job_data["deadline"]

    # Tags as multi-select
    if job_data.get("tags"):
        fields["Tags"] = [{"name": t} for t in job_data["tags"]]

    # Location
    loc = job_data.get("location")
    if loc:
        fields["Location Type"] = loc.get("type", "")
        cities = loc.get("cities", [])
        if cities:
            fields["Cities"] = ", ".join(cities)

    # Salary
    sal = job_data.get("salary")
    if sal:
        if sal.get("min") is not None:
            fields["Salary Min"] = sal["min"]
        if sal.get("max") is not None:
            fields["Salary Max"] = sal["max"]
        if sal.get("currency"):
            fields["Salary Currency"] = sal["currency"]
        if sal.get("period"):
            fields["Salary Period"] = sal["period"]

    # Remove None values — Airtable doesn't accept null for some field types
    return {k: v for k, v in fields.items() if v is not None}


def map_org_fields(org_data):
    """Map an org JSON record to Airtable field names/types."""
    fields = {
        "git_id": org_data["id"],
        "Name": org_data.get("name", ""),
    }

    if org_data.get("website"):
        fields["Website"] = org_data["website"]
    if org_data.get("hq_location"):
        fields["HQ Location"] = org_data["hq_location"]
    if org_data.get("size_estimate"):
        fields["Size Estimate"] = org_data["size_estimate"]
    if org_data.get("notes"):
        fields["Notes"] = org_data["notes"]

    # Multi-select fields
    if org_data.get("cause_areas"):
        fields["Cause Areas"] = [{"name": c} for c in org_data["cause_areas"]]
    if org_data.get("aliases"):
        fields["Aliases"] = ", ".join(org_data["aliases"])

    return {k: v for k, v in fields.items() if v is not None}


# --- Data Loading ---

def load_job(job_id):
    """Load a single job record by ID."""
    path = JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def load_org(org_id):
    """Load a single org record by ID."""
    path = ORGS_DIR / f"{org_id}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def load_all_jobs():
    """Load all job records from data/jobs/."""
    jobs = []
    if not JOBS_DIR.exists():
        return jobs
    for path in sorted(JOBS_DIR.glob("*.json")):
        with open(path) as f:
            jobs.append(json.load(f))
    return jobs


def load_all_orgs():
    """Load all org records from data/orgs/."""
    orgs = []
    if not ORGS_DIR.exists():
        return orgs
    for path in sorted(ORGS_DIR.glob("*.json")):
        with open(path) as f:
            orgs.append(json.load(f))
    return orgs


def load_ids_file(path):
    """Load a JSON file containing a list of IDs to sync."""
    filepath = Path(path)
    if not filepath.exists():
        print(f"Error: IDs file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(filepath) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "ids" in data:
        return data["ids"]
    print(f"Error: IDs file must contain a JSON array or object with 'ids' key", file=sys.stderr)
    sys.exit(1)


def apply_filters(records, filters):
    """Filter records by key=value pairs (dot notation supported)."""
    filtered = []
    for rec in records:
        match = True
        for f in filters:
            if "=" not in f:
                log(f"Warning: invalid filter '{f}' (expected key=value)")
                match = False
                break
            key, value = f.split("=", 1)
            # Support dot notation for nested fields
            parts = key.split(".")
            obj = rec
            for part in parts:
                if isinstance(obj, dict):
                    obj = obj.get(part)
                else:
                    obj = None
                    break
            if str(obj) != value:
                match = False
                break
        if match:
            filtered.append(rec)
    return filtered


# --- Sync Logic ---

def sync_records(client, jobs, orgs, dry_run=False, force=False):
    """Sync job and org records to Airtable. Returns result dict."""
    result = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}

    total_to_sync = len(jobs) + len(orgs)
    if total_to_sync == 0:
        log("No records to sync.")
        return result

    # Record count check (skip for dry run)
    if not dry_run:
        try:
            current_count = client.get_record_count()
            projected = current_count + total_to_sync
            log(f"Syncing {total_to_sync} records. Current: {current_count}/{RECORD_LIMIT}. After: {projected}/{RECORD_LIMIT} (max).")

            if current_count >= ERROR_THRESHOLD and not force:
                log(f"ERROR: Record count ({current_count}) at {current_count*100//RECORD_LIMIT}% capacity. Use --force to override.")
                sys.exit(1)
            elif current_count >= WARNING_THRESHOLD:
                log(f"WARNING: Record count ({current_count}) at {current_count*100//RECORD_LIMIT}% of free tier capacity.")
        except Exception as e:
            log(f"Warning: Could not check record count: {e}")

    # Get existing records for dedup
    jobs_table = getattr(client, 'jobs_table', 'Jobs')
    orgs_table = getattr(client, 'orgs_table', 'Organizations')

    if not dry_run:
        try:
            existing_jobs = client.get_existing_records(jobs_table)
            existing_orgs = client.get_existing_records(orgs_table)
        except Exception as e:
            log(f"Warning: Could not fetch existing records: {e}")
            existing_jobs = {}
            existing_orgs = {}
    else:
        existing_jobs = {}
        existing_orgs = {}

    # Sync orgs first (jobs reference orgs)
    log(f"\nSyncing {len(orgs)} org(s)...")
    for org in orgs:
        org_id = org["id"]
        fields = map_org_fields(org)
        try:
            if org_id in existing_orgs:
                if dry_run:
                    client.update_record(orgs_table, "dry_run", fields)
                else:
                    client.update_record(orgs_table, existing_orgs[org_id], fields)
                result["updated"] += 1
            else:
                client.create_record(orgs_table, fields)
                result["created"] += 1
        except Exception as e:
            log(f"  Error syncing org '{org_id}': {e}")
            result["errors"] += 1

    # Sync jobs
    log(f"Syncing {len(jobs)} job(s)...")
    for job in jobs:
        job_id = job["id"]
        fields = map_job_fields(job)
        try:
            if job_id in existing_jobs:
                if dry_run:
                    client.update_record(jobs_table, "dry_run", fields)
                else:
                    client.update_record(jobs_table, existing_jobs[job_id], fields)
                result["updated"] += 1
            else:
                client.create_record(jobs_table, fields)
                result["created"] += 1
        except Exception as e:
            log(f"  Error syncing job '{job_id}': {e}")
            result["errors"] += 1

    return result


# --- CLI ---

def build_parser():
    """Build argument parser."""
    parser = argparse.ArgumentParser(
        description="Sync EA Jobs Database records to Airtable.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --dry-run --all                    # Preview what would sync
  %(prog)s --ids job-id-1 job-id-2            # Sync specific records
  %(prog)s --ids-file exports/curated.json    # Sync from curated list
  %(prog)s --all --output-json                # Sync all, JSON output
  %(prog)s --filter "status=open" --dry-run   # Filter and preview
        """,
    )

    # Source selection (mutually exclusive)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--ids", nargs="+", metavar="ID",
        help="Sync specific records by ID (job or org IDs)"
    )
    source.add_argument(
        "--ids-file", metavar="PATH",
        help="Sync records listed in a JSON file"
    )
    source.add_argument(
        "--all", action="store_true",
        help="Sync all records from data/jobs/ and data/orgs/"
    )

    # Options
    parser.add_argument(
        "--filter", action="append", dest="filters", metavar="KEY=VALUE",
        help="Filter records by field value (e.g. status=open). Can be repeated."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be synced without modifying Airtable"
    )
    parser.add_argument(
        "--output-json", action="store_true",
        help="Output structured JSON result to stdout"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Override record count safety limits"
    )

    return parser


def resolve_records(args):
    """Resolve which jobs and orgs to sync based on CLI args."""
    jobs = []
    orgs = []

    if args.all:
        jobs = load_all_jobs()
        orgs = load_all_orgs()
        if not jobs and not orgs:
            log("Error: No records found in data/jobs/ or data/orgs/")
            sys.exit(1)
        if len(jobs) + len(orgs) > 500:
            log(f"Warning: Syncing {len(jobs) + len(orgs)} records. Use --dry-run first to preview.")
    elif args.ids_file:
        ids = load_ids_file(args.ids_file)
        for record_id in ids:
            job = load_job(record_id)
            if job:
                jobs.append(job)
            else:
                org = load_org(record_id)
                if org:
                    orgs.append(org)
                else:
                    log(f"Warning: Record '{record_id}' not found in data/jobs/ or data/orgs/")
    elif args.ids:
        for record_id in args.ids:
            job = load_job(record_id)
            if job:
                jobs.append(job)
            else:
                org = load_org(record_id)
                if org:
                    orgs.append(org)
                else:
                    log(f"Warning: Record '{record_id}' not found in data/jobs/ or data/orgs/")

    # Apply filters (only to jobs — orgs don't have the same filterable fields)
    if args.filters:
        jobs = apply_filters(jobs, args.filters)

    return jobs, orgs


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Resolve records to sync
    jobs, orgs = resolve_records(args)

    log(f"Selected {len(jobs)} job(s) and {len(orgs)} org(s) for sync.")

    # Create client
    if args.dry_run:
        client = DryRunClient()
    else:
        api_key = os.environ.get("AIRTABLE_API_KEY")
        base_id = os.environ.get("AIRTABLE_BASE_ID")
        if not api_key or not base_id:
            log("Error: AIRTABLE_API_KEY and AIRTABLE_BASE_ID environment variables are required.")
            log("Set them or use --dry-run to preview without Airtable access.")
            sys.exit(1)
        jobs_table = os.environ.get("AIRTABLE_JOBS_TABLE_ID", "Jobs")
        orgs_table = os.environ.get("AIRTABLE_ORGS_TABLE_ID", "Organizations")
        client = AirtableClient(api_key, base_id, jobs_table, orgs_table)

    # Sync
    result = sync_records(client, jobs, orgs, dry_run=args.dry_run, force=args.force)

    # Output
    if args.output_json:
        print(json.dumps(result))
    else:
        log(f"\nSync complete: {result['created']} created, {result['updated']} updated, "
            f"{result['skipped']} skipped, {result['errors']} errors.")

    # Exit with error code if there were errors
    if result["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
