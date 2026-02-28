#!/usr/bin/env python3
"""Fetch job listings from 80,000 Hours via their Algolia search API.

Usage:
    python3 scripts/fetch_80k_hours.py [--dry-run] [--since YYYY-MM-DD] [--limit N]

Fetches all jobs from the 80K Hours job board (Algolia index), converts them
to the project's JSON schema format, and saves JDs as markdown files.
"""

import glob as globmod
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from algoliasearch.search.client import SearchClientSync
except ImportError:
    print("ERROR: algoliasearch not installed. Run: pip3 install algoliasearch", file=sys.stderr)
    sys.exit(1)

try:
    from markdownify import markdownify as md
except ImportError:
    print("ERROR: markdownify not installed. Run: pip3 install markdownify", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ALGOLIA_APP_ID = "W6KM1UDIB3"
ALGOLIA_API_KEY = "d1d7f2c8696e7b36837d5ed337c4a319"
JOBS_INDEX = "jobs_prod_super_ranked"
COMPANIES_INDEX = "companies_prod"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_JOBS = PROJECT_ROOT / "data" / "jobs"
DATA_ORGS = PROJECT_ROOT / "data" / "orgs"
DATA_JDS = PROJECT_ROOT / "data" / "jds"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(text):
    """Convert text to a lowercase slug suitable for IDs."""
    text = text.lower().strip()
    text = re.sub(r"[''']", "", text)
    text = text.replace(",", "")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text


def make_job_id(org_slug, title_slug, year_month):
    """Create a job ID in the standard format."""
    return f"{org_slug}--{title_slug}--{year_month}"


def unix_to_date(ts):
    """Convert unix timestamp to YYYY-MM-DD string, or None."""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return None


def unix_to_year_month(ts):
    """Convert unix timestamp to YYYY-MM string."""
    if not ts:
        return date.today().strftime("%Y-%m")
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m")
    except (ValueError, TypeError, OSError):
        return date.today().strftime("%Y-%m")


def parse_salary(salary_text):
    """Parse salary text like '$140,000 - $170,000 award' into a salary object.

    Returns a dict with min, max, currency, period or None if unparseable.
    """
    if not salary_text or salary_text.strip() == "":
        return None

    text = salary_text.strip()

    # Detect currency
    currency = "USD"
    if "£" in text:
        currency = "GBP"
    elif "€" in text:
        currency = "EUR"
    elif "CHF" in text:
        currency = "CHF"

    # Detect period
    period = "annual"
    if "per hour" in text.lower() or "/hour" in text.lower() or "/hr" in text.lower():
        period = "hourly"
        # We only support annual/monthly in schema, skip hourly
        return None
    if "per month" in text.lower() or "/month" in text.lower():
        period = "monthly"

    # Extract numbers
    numbers = re.findall(r'[\$£€]?\s*([\d,]+(?:\.\d+)?)', text)
    if not numbers:
        return None

    nums = []
    for n in numbers:
        try:
            nums.append(float(n.replace(",", "")))
        except ValueError:
            continue

    if not nums:
        return None

    salary = {"currency": currency, "period": period}
    if len(nums) >= 2:
        salary["min"] = nums[0]
        salary["max"] = nums[1]
    else:
        salary["min"] = nums[0]
        salary["max"] = nums[0]

    return salary


def determine_location_type(tags_location_type, tags_city):
    """Determine location type from 80K Hours tags."""
    loc_types = [t.lower() for t in (tags_location_type or [])]
    cities = tags_city or []

    if "remote" in loc_types:
        return "remote"
    # Check city tags for remote indicators
    for city in cities:
        if "remote" in city.lower():
            return "remote"
    if "hybrid" in loc_types:
        return "hybrid"
    if cities:
        return "onsite"
    return "remote"  # default if no location info


def clean_cities(tags_city):
    """Clean city tags, removing 'Remote' entries."""
    if not tags_city:
        return []
    return [c for c in tags_city if "remote" not in c.lower()]


def html_to_markdown(html_content):
    """Convert HTML to clean markdown using markdownify."""
    if not html_content:
        return ""
    result = md(html_content, heading_style="ATX", strip=["img"])
    # Clean up excessive whitespace
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


# ---------------------------------------------------------------------------
# API connectivity check
# ---------------------------------------------------------------------------

def check_api_connectivity():
    """Fail fast if Algolia API credentials don't work.

    Returns the client if successful, exits with error if not.
    """
    try:
        client = SearchClientSync(ALGOLIA_APP_ID, ALGOLIA_API_KEY)
        result = client.search_single_index(JOBS_INDEX, {"hitsPerPage": 1})
        if not result.hits:
            print("ERROR: Algolia API returned no results. Index may be empty.", file=sys.stderr)
            sys.exit(1)
        print(f"API check passed: {result.nb_hits} jobs in index", file=sys.stderr)
        return client
    except Exception as e:
        print(f"ERROR: Algolia API connectivity check failed: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Fetch from Algolia
# ---------------------------------------------------------------------------

def fetch_all_jobs(client, since_date=None):
    """Fetch all jobs from the Algolia index.

    Args:
        client: Algolia SearchClientSync instance
        since_date: Optional date string (YYYY-MM-DD) to filter by posted_at

    Returns list of dicts (raw Algolia records).
    """
    all_hits = []
    page = 0
    total_pages = 1

    while page < total_pages:
        params = {"hitsPerPage": 1000, "page": page}

        # Add date filter if --since provided
        if since_date:
            try:
                dt = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                since_ts = int(dt.timestamp())
                params["numericFilters"] = [f"posted_at>={since_ts}"]
            except ValueError:
                print(f"WARNING: Invalid --since date '{since_date}', ignoring filter", file=sys.stderr)

        result = client.search_single_index(JOBS_INDEX, params)
        total_pages = result.nb_pages

        for hit in result.hits:
            all_hits.append(hit.to_dict())

        page += 1

    # Strip Algolia highlight metadata
    for hit in all_hits:
        hit.pop("_highlightResult", None)
        hit.pop("_snippetResult", None)

    print(f"Fetched {len(all_hits)} jobs from Algolia", file=sys.stderr)
    return all_hits


def fetch_all_companies(client):
    """Fetch all companies from the Algolia index.

    Returns list of dicts (raw Algolia records).
    """
    all_hits = []
    page = 0
    total_pages = 1

    while page < total_pages:
        result = client.search_single_index(COMPANIES_INDEX, {"hitsPerPage": 1000, "page": page})
        total_pages = result.nb_pages

        for hit in result.hits:
            d = hit.to_dict()
            d.pop("_highlightResult", None)
            d.pop("_snippetResult", None)
            all_hits.append(d)

        page += 1

    print(f"Fetched {len(all_hits)} companies from Algolia", file=sys.stderr)
    return all_hits


# ---------------------------------------------------------------------------
# Convert to our schema
# ---------------------------------------------------------------------------

def convert_job(algolia_record):
    """Convert an Algolia job record to our job schema format.

    Returns (job_dict, jd_markdown) tuple.
    """
    title = algolia_record.get("title", "Untitled")
    org_name = algolia_record.get("company_name", "unknown")
    org_slug = slugify(org_name)
    posted_at = algolia_record.get("posted_at")
    year_month = unix_to_year_month(posted_at)

    title_slug = slugify(title)
    job_id = make_job_id(org_slug, title_slug, year_month)

    # Location
    loc_type = determine_location_type(
        algolia_record.get("tags_location_type", []),
        algolia_record.get("tags_city", [])
    )
    cities = clean_cities(algolia_record.get("tags_city", []))
    location = {"type": loc_type}
    if cities:
        location["cities"] = cities

    # Salary
    salary = parse_salary(algolia_record.get("salary", ""))

    # Tags - combine area and role type tags
    tags = []
    for tag in (algolia_record.get("tags_area", []) or []):
        tags.append(slugify(tag))
    for tag in (algolia_record.get("tags_role_type", []) or []):
        tags.append(slugify(tag))
    for tag in (algolia_record.get("tags_skill", []) or []):
        tags.append(slugify(tag))

    # Deadlines
    posted_date = unix_to_date(posted_at)
    deadline = unix_to_date(algolia_record.get("closes_at"))

    # Build job record
    job = {
        "id": job_id,
        "title": title,
        "organization": org_slug,
        "source": "80k-hours",
        "source_url": algolia_record.get("url_external"),
        "jd_file": None,
        "location": location,
        "salary": salary,
        "posted_date": posted_date,
        "deadline": deadline,
        "date_added": date.today().isoformat(),
        "tags": tags,
        "status": "unknown",
        "confidence": 1.0,
        "notes": None,
    }

    # JD markdown from description_short HTML
    jd_html = algolia_record.get("description_short", "")
    jd_md = html_to_markdown(jd_html)

    if jd_md:
        job["jd_file"] = f"data/jds/{job_id}.md"

    return job, jd_md


def convert_company(algolia_company):
    """Convert an Algolia company record to our org schema format."""
    name = algolia_company.get("name", "Unknown")
    org_id = slugify(name)

    # Extract website
    website = algolia_company.get("url") or None

    # Cause areas from problem_areas
    cause_areas = []
    for area in (algolia_company.get("problem_areas", []) or []):
        cause_areas.append(area)

    # HQ location
    hq = algolia_company.get("hq", "")
    hq_location = hq.replace(".", ", ") if hq else None

    # Size
    size = algolia_company.get("org_size") or None

    org = {
        "id": org_id,
        "name": name,
        "aliases": [],
        "website": website,
        "cause_areas": cause_areas,
        "hq_location": hq_location,
        "size_estimate": size,
        "notes": None,
    }

    return org


# ---------------------------------------------------------------------------
# Cross-source deduplication
# ---------------------------------------------------------------------------

def load_existing_jobs():
    """Load all existing job records from data/jobs/."""
    jobs = {}
    for filepath in DATA_JOBS.glob("*.json"):
        if filepath.name == ".gitkeep":
            continue
        with open(filepath) as f:
            job = json.load(f)
        jobs[job["id"]] = job
    return jobs


def load_existing_orgs():
    """Load all existing org records from data/orgs/."""
    orgs = {}
    for filepath in DATA_ORGS.glob("*.json"):
        if filepath.name == ".gitkeep":
            continue
        with open(filepath) as f:
            org = json.load(f)
        orgs[org["id"]] = org
    return orgs


def find_duplicate(new_job, existing_jobs):
    """Check if a new job is a duplicate of an existing one.

    Match on (org + similar title + approximate date).
    Returns the existing job ID if duplicate found, else None.
    """
    org = new_job["organization"]
    title_slug = slugify(new_job["title"])
    new_date = new_job.get("posted_date", "")

    for existing_id, existing in existing_jobs.items():
        if existing.get("source") == "80k-hours":
            continue  # Don't dedup against our own records

        if existing.get("organization") != org:
            continue

        # Check title similarity (exact slug match)
        existing_title_slug = slugify(existing.get("title", ""))
        if existing_title_slug != title_slug:
            continue

        # Check date proximity (same month)
        existing_date = existing.get("posted_date", "")
        if new_date and existing_date:
            if new_date[:7] == existing_date[:7]:
                return existing_id

        # If no dates, title+org match is enough
        if not new_date or not existing_date:
            return existing_id

    return None


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------

def save_job(job, dry_run=False):
    """Save a job record to data/jobs/."""
    filepath = DATA_JOBS / f"{job['id']}.json"
    if dry_run:
        return
    DATA_JOBS.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(job, f, indent=2)
        f.write("\n")


def save_jd(job_id, jd_content, source_url, dry_run=False):
    """Save a JD markdown file to data/jds/."""
    if not jd_content:
        return
    filepath = DATA_JDS / f"{job_id}.md"
    if dry_run:
        return
    DATA_JDS.mkdir(parents=True, exist_ok=True)

    frontmatter = (
        f"---\n"
        f"job_id: {job_id}\n"
        f"source_url: {source_url or ''}\n"
        f"fetched_date: {date.today().isoformat()}\n"
        f"platform: 80k-hours\n"
        f"---\n\n"
    )

    with open(filepath, "w") as f:
        f.write(frontmatter + jd_content + "\n")


def save_org(org, dry_run=False):
    """Save or merge an org record to data/orgs/."""
    filepath = DATA_ORGS / f"{org['id']}.json"
    if dry_run:
        return

    DATA_ORGS.mkdir(parents=True, exist_ok=True)

    # Merge with existing if present (preserve manual data)
    if filepath.exists():
        with open(filepath) as f:
            existing = json.load(f)
        # Only update fields that are empty/null in existing
        for key in ["website", "hq_location", "size_estimate"]:
            if not existing.get(key) and org.get(key):
                existing[key] = org[key]
        # Merge cause_areas
        existing_areas = set(existing.get("cause_areas", []))
        new_areas = set(org.get("cause_areas", []))
        existing["cause_areas"] = sorted(existing_areas | new_areas)
        org = existing

    with open(filepath, "w") as f:
        json.dump(org, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process(client, dry_run=False, since_date=None, limit=None):
    """Main processing pipeline.

    Returns a summary dict.
    """
    summary = {
        "total_fetched": 0,
        "jobs_new": 0,
        "jobs_updated": 0,
        "orgs_created": 0,
        "orgs_updated": 0,
        "jds_saved": 0,
        "duplicates_found": 0,
        "skipped": 0,
    }

    # Fetch from Algolia
    raw_jobs = fetch_all_jobs(client, since_date=since_date)
    raw_companies = fetch_all_companies(client)
    summary["total_fetched"] = len(raw_jobs)

    # Load existing data for dedup
    existing_jobs = load_existing_jobs()
    existing_orgs = load_existing_orgs()

    # Process companies first
    for company in raw_companies:
        org = convert_company(company)
        if org["id"] in existing_orgs:
            summary["orgs_updated"] += 1
        else:
            summary["orgs_created"] += 1
        save_org(org, dry_run=dry_run)

    # Process jobs
    processed = 0
    seen_ids = set()

    for raw_job in raw_jobs:
        if limit and processed >= limit:
            break

        job, jd_md = convert_job(raw_job)

        # Handle duplicate job IDs within 80K Hours data
        # (same org + title + month can happen)
        if job["id"] in seen_ids:
            # Append objectID suffix to make unique
            obj_id = raw_job.get("objectID", str(processed))
            job["id"] = f"{job['id']}-{obj_id}"
            if jd_md:
                job["jd_file"] = f"data/jds/{job['id']}.md"

        seen_ids.add(job["id"])

        # Cross-source dedup
        dup_id = find_duplicate(job, existing_jobs)
        if dup_id:
            summary["duplicates_found"] += 1
            # Add cross-reference note
            job["notes"] = f"Also found in: {dup_id}"
            print(f"  DEDUP: {job['id']} matches {dup_id}", file=sys.stderr)

        # Check if updating existing
        if job["id"] in existing_jobs:
            summary["jobs_updated"] += 1
        else:
            summary["jobs_new"] += 1

        # Also create org if not in companies index
        org_slug = job["organization"]
        if org_slug not in existing_orgs:
            org_name = raw_job.get("company_name", org_slug)
            org = {
                "id": org_slug,
                "name": org_name,
                "aliases": [],
                "website": raw_job.get("company_url") or None,
                "cause_areas": [],
                "hq_location": None,
                "size_estimate": None,
                "notes": None,
            }
            save_org(org, dry_run=dry_run)
            existing_orgs[org_slug] = org
            summary["orgs_created"] += 1

        save_job(job, dry_run=dry_run)

        if jd_md:
            save_jd(job["id"], jd_md, job.get("source_url"), dry_run=dry_run)
            summary["jds_saved"] += 1

        processed += 1

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_help():
    """Print usage information."""
    print("""EA Jobs Database — 80K Hours Fetcher

Usage:
    python3 scripts/fetch_80k_hours.py [OPTIONS]

Options:
    --dry-run         Preview what would be fetched/written without saving files
    --since DATE      Only fetch jobs posted after DATE (YYYY-MM-DD)
    --limit N         Limit to N jobs (for testing)
    --help            Show this help message

Examples:
    python3 scripts/fetch_80k_hours.py                          # Full import
    python3 scripts/fetch_80k_hours.py --since 2026-01-01       # Incremental
    python3 scripts/fetch_80k_hours.py --dry-run                # Preview
    python3 scripts/fetch_80k_hours.py --dry-run --limit 10     # Quick test
""")


def main(argv=None):
    """Main entry point."""
    if argv is None:
        argv = sys.argv

    if "--help" in argv or "-h" in argv:
        print_help()
        return 0

    dry_run = "--dry-run" in argv
    since_date = None
    limit = None

    if "--since" in argv:
        idx = argv.index("--since")
        if idx + 1 < len(argv):
            since_date = argv[idx + 1]

    if "--limit" in argv:
        idx = argv.index("--limit")
        if idx + 1 < len(argv):
            limit = int(argv[idx + 1])

    print("EA Jobs Database — 80K Hours Fetcher", file=sys.stderr)
    print("=" * 40, file=sys.stderr)

    if dry_run:
        print("DRY RUN — no files will be written", file=sys.stderr)

    # API connectivity pre-check
    client = check_api_connectivity()

    # Process
    summary = process(client, dry_run=dry_run, since_date=since_date, limit=limit)

    # Print summary
    print(f"\nSummary:", file=sys.stderr)
    print(f"  Total fetched: {summary['total_fetched']}", file=sys.stderr)
    print(f"  New jobs: {summary['jobs_new']}", file=sys.stderr)
    print(f"  Updated jobs: {summary['jobs_updated']}", file=sys.stderr)
    print(f"  Orgs created: {summary['orgs_created']}", file=sys.stderr)
    print(f"  Orgs updated: {summary['orgs_updated']}", file=sys.stderr)
    print(f"  JDs saved: {summary['jds_saved']}", file=sys.stderr)
    print(f"  Duplicates found: {summary['duplicates_found']}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
