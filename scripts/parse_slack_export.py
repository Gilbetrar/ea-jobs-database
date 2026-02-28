#!/usr/bin/env python3
"""Parse EA Slack job channel export into structured JSON job and org records.

Usage:
    python3 scripts/parse_slack_export.py [path_to_slack_export.md]

The Slack export path can be provided as:
  1. Command-line argument
  2. EA_SLACK_EXPORT_PATH environment variable
  3. slack_export_path key in config.json at repo root
"""

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

# Project root is one level up from scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_JOBS = PROJECT_ROOT / "data" / "jobs"
DATA_ORGS = PROJECT_ROOT / "data" / "orgs"
EXPORTS = PROJECT_ROOT / "exports"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def get_export_path(argv=None):
    """Resolve Slack export path from CLI arg, env var, or config.json."""
    # 1. CLI argument
    if argv and len(argv) > 1:
        return argv[1]
    # 2. Environment variable
    env_path = os.environ.get("EA_SLACK_EXPORT_PATH")
    if env_path:
        return env_path
    # 3. config.json
    config_file = PROJECT_ROOT / "config.json"
    if config_file.is_file():
        with open(config_file) as f:
            cfg = json.load(f)
        path = cfg.get("slack_export_path")
        if path:
            return path
    return None


# ---------------------------------------------------------------------------
# Text normalization helpers
# ---------------------------------------------------------------------------

def slugify(text):
    """Convert text to a lowercase slug suitable for IDs."""
    text = text.lower().strip()
    text = re.sub(r"[''']", "", text)  # remove apostrophes
    text = text.replace(",", "")  # remove commas (e.g. "80,000" -> "80000")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text


def make_job_id(org_slug, title_slug, year_month):
    """Build a job ID following the convention: org--role--YYYY-MM."""
    return f"{org_slug}--{title_slug}--{year_month}"


# ---------------------------------------------------------------------------
# Salary parsing
# ---------------------------------------------------------------------------

CURRENCY_SYMBOLS = {
    "$": "USD",
    "£": "GBP",
    "€": "EUR",
    "CHF": "CHF",
    "₹": "INR",
}

# Matches patterns like: $85,000 - $110,000/year  |  £35,000 - £45,000/year
# Also: €55,000 - €75,000 per year  |  CHF 80,000 - CHF 100,000/year
SALARY_PATTERN = re.compile(
    r"(?P<curr_prefix>[£$€₹]|CHF)\s*"
    r"(?P<min>[\d,]+(?:\.\d+)?)\s*[kK]?\s*"
    r"(?:[-–—to]+\s*(?:[£$€₹]|CHF)?\s*"
    r"(?P<max>[\d,]+(?:\.\d+)?)\s*[kK]?)?\s*"
    r"(?:/|\s+per\s+)?\s*"
    r"(?P<period>year|annual|annually|annum|month|monthly|per\s+year|per\s+month|p\.?a\.?)?",
    re.IGNORECASE,
)


def parse_salary(text):
    """Extract salary information from text. Returns dict or None."""
    match = SALARY_PATTERN.search(text)
    if not match:
        return None

    prefix = match.group("curr_prefix").strip()
    currency = CURRENCY_SYMBOLS.get(prefix, prefix.upper())

    min_str = match.group("min").replace(",", "")
    min_val = int(float(min_str))
    # Handle "k" notation (e.g. "$80-100k")
    if min_val < 1000 and "k" in text[match.start():match.end()].lower():
        min_val *= 1000

    max_val = None
    max_str = match.group("max")
    if max_str:
        max_val = int(float(max_str.replace(",", "")))
        if max_val < 1000 and "k" in text[match.start():match.end()].lower():
            max_val *= 1000

    period_str = (match.group("period") or "").lower().strip()
    if period_str in ("month", "monthly", "per month"):
        period = "monthly"
    else:
        period = "annual"

    result = {"currency": currency, "period": period}
    if min_val:
        result["min"] = min_val
    if max_val:
        result["max"] = max_val
    elif min_val:
        # Single value — put it in both min and max
        result["max"] = min_val

    return result


# ---------------------------------------------------------------------------
# Location parsing
# ---------------------------------------------------------------------------

def parse_location(text):
    """Extract location info from text. Returns dict with type and cities."""
    text_lower = text.lower()

    # Determine location type
    has_remote = "remote" in text_lower
    has_hybrid = "hybrid" in text_lower
    has_onsite = "onsite" in text_lower or "on-site" in text_lower or "in office" in text_lower
    # "City or Remote" means hybrid
    has_city_or_remote = bool(re.search(r"\b[A-Z][a-z]+.*\bor\s+[Rr]emote\b", text))

    if has_hybrid or has_city_or_remote:
        loc_type = "hybrid"
    elif has_remote:
        loc_type = "remote"
    elif has_onsite:
        loc_type = "onsite"
    else:
        loc_type = "onsite"  # default if a specific city is mentioned

    # Valid US state and common country abbreviations
    VALID_CODES = {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC", "UK", "US",
    }

    # Extract cities
    cities = []
    city_patterns = [
        # "in/at/based in City, State/Country" (limit to short phrases)
        r"(?:in|at|based in|location:\s*)\s*([A-Z][a-zA-Z\s]{1,25},\s*[A-Z][A-Za-z\s]{1,20})",
        # "City, XX" (two-letter state/country code) — validate the code
        r"([A-Z][a-zA-Z\s]{1,25},\s*([A-Z]{2}))\b",
        # Known cities
        r"\b(London|Oxford|San Francisco|Washington|New York|Berlin|Basel|Geneva)\b",
    ]
    for i, pattern in enumerate(city_patterns):
        for m in re.finditer(pattern, text):
            if i == 1:
                # Validate the 2-letter code is a real state/country
                code = m.group(2)
                if code not in VALID_CODES:
                    continue
                city = m.group(1).strip().rstrip(".")
            else:
                city = m.group(1).strip().rstrip(".")
            # Skip overly long matches (likely sentences, not city names)
            if len(city) > 40:
                continue
            if city not in cities:
                cities.append(city)

    # Enhance bare city names with country context
    enhanced = []
    for city in cities:
        if "," not in city:
            # Try to find "City, Country" in original text
            ctx = re.search(
                re.escape(city) + r",?\s*([A-Z][A-Za-z\s]{1,15}?)(?:\s*[\(\)]|\s*$|\s*\n)",
                text,
            )
            if ctx:
                suffix = ctx.group(1).strip()
                if len(suffix) <= 15:
                    enhanced.append(f"{city}, {suffix}")
                else:
                    enhanced.append(city)
            else:
                enhanced.append(city)
        else:
            enhanced.append(city)

    # Deduplicate — keep longest form of each city, remove exact duplicates
    seen = set()
    final_cities = []
    for c in enhanced:
        if c in seen:
            continue
        seen.add(c)
        base = c.split(",")[0].strip()
        if not any(base in existing for existing in final_cities if existing != c):
            final_cities.append(c)

    if not final_cities and loc_type == "onsite":
        loc_type = "remote"  # no city found, probably remote

    result = {"type": loc_type}
    if final_cities:
        result["cities"] = final_cities
    else:
        result["cities"] = []

    return result


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

MONTH_NAMES = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def parse_date(text):
    """Extract a date from text. Returns YYYY-MM-DD string or None."""
    # ISO format
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if m:
        return m.group(1)

    # "Month DD, YYYY" or "DD Month YYYY"
    m = re.search(
        r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b", text
    )
    if m:
        month_str = m.group(1).lower()
        if month_str in MONTH_NAMES:
            day = int(m.group(2))
            year = m.group(3)
            return f"{year}-{MONTH_NAMES[month_str]}-{day:02d}"

    m = re.search(
        r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b", text
    )
    if m:
        month_str = m.group(2).lower()
        if month_str in MONTH_NAMES:
            day = int(m.group(1))
            year = m.group(3)
            return f"{year}-{MONTH_NAMES[month_str]}-{day:02d}"

    return None


def parse_deadline(text):
    """Extract deadline date from text."""
    # Look for deadline-specific context
    deadline_patterns = [
        r"(?:deadline|apply\s+by|applications?\s+(?:close|due|by))[\s:]*(.+?)(?:\n|$)",
        r"(?:closing\s+date|due\s+date)[\s:]*(.+?)(?:\n|$)",
    ]
    for pattern in deadline_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            d = parse_date(m.group(1))
            if d:
                return d

    # Check for "rolling" deadline
    if re.search(r"\brolling\s+(?:deadline|basis)\b", text, re.IGNORECASE):
        return None

    return None


# ---------------------------------------------------------------------------
# URL extraction
# ---------------------------------------------------------------------------

URL_PATTERN = re.compile(r"https?://[^\s\)>\]]+")


def extract_urls(text):
    """Extract all URLs from text."""
    return URL_PATTERN.findall(text)


def find_apply_url(urls):
    """Find the most likely application URL from a list of URLs."""
    for url in urls:
        url_lower = url.lower()
        if any(kw in url_lower for kw in ["career", "jobs", "apply", "hiring", "position"]):
            return url.rstrip(".,;:")
    return urls[0].rstrip(".,;:") if urls else None


# ---------------------------------------------------------------------------
# Post classification
# ---------------------------------------------------------------------------

JOB_KEYWORDS = [
    "hiring", "job", "role", "position", "vacancy", "opening",
    "salary", "compensation", "apply", "application", "deadline",
    "we're looking for", "we are looking for", "join our team",
    "full-time", "part-time", "contract",
]

NOT_JOB_KEYWORDS = [
    "conference", "registration", "fellowship", "program application",
    "does anyone", "any advice", "recommendations",
    "reminder about", "event", "meetup", "workshop",
    "summer program", "internship program", "stipend",
]


def classify_post(text):
    """Classify a post as job_posting, multi_role_post, or not_a_job.

    Returns: (classification, confidence_modifier)
    """
    text_lower = text.lower()

    # Check for non-job indicators
    not_job_score = sum(1 for kw in NOT_JOB_KEYWORDS if kw in text_lower)
    job_score = sum(1 for kw in JOB_KEYWORDS if kw in text_lower)

    if not_job_score > job_score:
        return "not_a_job", 0.0

    # Check for multiple numbered roles
    numbered_roles = re.findall(r"\d+\.\s+\*\*[^*]+\*\*", text)
    if len(numbered_roles) >= 2:
        return "multi_role_post", 0.85

    if job_score >= 2:
        return "job_posting", 0.9
    elif job_score == 1:
        return "job_posting", 0.7
    else:
        return "not_a_job", 0.0


# ---------------------------------------------------------------------------
# Organization extraction
# ---------------------------------------------------------------------------

def extract_org_name(text):
    """Extract organization name from post text."""
    # Pattern: "**OrgName — Title**" or "**OrgName is hiring..."
    # Allow digits in org names (e.g. "80,000 Hours")
    patterns = [
        # "Org Name (ABBR) — ..." bold header
        r"\*\*([A-Z0-9][A-Za-z0-9\s&,.']+?)\s*\([A-Z]+\)\s*[-—–]",
        # "at OrgName" (allow digits/commas for names like "80,000 Hours")
        r"\bat\s+([A-Z0-9][A-Za-z0-9\s&,.']+?)(?:\s*[-—–]|\s*is\b|\s*\n)",
        # "**OrgName — ..." bold header without abbreviation
        r"\*\*([A-Z0-9][A-Za-z0-9\s&,.']+?)(?:\s*[-—–])",
        # "OrgName is hiring/looking"
        r"([A-Z0-9][A-Za-z0-9\s&,.']+?)\s+is\s+(?:hiring|looking|seeking)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            name = m.group(1).strip().rstrip(".,;:")
            # Clean up common artifacts
            name = re.sub(r"\s*\([^)]*\)\s*$", "", name)  # remove trailing parens
            # Skip poster names and generic words
            if len(name) > 2 and name not in ("Hiring", "Multiple Roles", "Sharing"):
                return name
    return None


def extract_org_aliases(text, org_name):
    """Extract aliases/abbreviations for an org from the text."""
    aliases = []
    # Look for parenthetical abbreviations: "Centre for Effective Altruism (CEA)"
    m = re.search(re.escape(org_name) + r"\s*\(([A-Z]{2,})\)", text)
    if m:
        aliases.append(m.group(1))
    # Look for abbreviations used later: "RP", "CEA", etc.
    if len(org_name.split()) >= 2:
        initials = "".join(w[0] for w in org_name.split() if w[0].isupper())
        if len(initials) >= 2 and initials in text:
            if initials not in aliases:
                aliases.append(initials)
    return aliases


def extract_org_website(urls, org_name):
    """Find the most likely org website from URLs."""
    org_slug = slugify(org_name)
    for url in urls:
        url_lower = url.lower()
        # Skip career/apply pages
        if any(kw in url_lower for kw in ["career", "jobs", "apply"]):
            continue
        if org_slug.replace("-", "") in url_lower.replace("-", "").replace(".", ""):
            return url.rstrip(".,;:")
    return None


def build_org_record(org_name, text, urls):
    """Build an organization record."""
    org_id = slugify(org_name)
    aliases = extract_org_aliases(text, org_name)
    website = extract_org_website(urls, org_name)

    # If no general website, derive from career URLs
    if not website:
        for url in urls:
            m = re.match(r"(https?://[^/]+)", url)
            if m:
                website = m.group(1)
                break

    # Extract cause areas from tags/context
    cause_areas = []
    text_lower = text.lower()
    cause_map = {
        "ai safety": "ai-safety",
        "ai governance": "ai-governance",
        "animal welfare": "animal-welfare",
        "global health": "global-health",
        "climate": "climate",
        "biosecurity": "biosecurity",
        "nuclear": "nuclear-security",
        "poverty": "global-poverty",
    }
    for keyword, area in cause_map.items():
        if keyword in text_lower and area not in cause_areas:
            cause_areas.append(area)

    return {
        "id": org_id,
        "name": org_name,
        "aliases": aliases,
        "website": website,
        "cause_areas": cause_areas,
        "hq_location": None,
        "size_estimate": None,
        "notes": None,
    }


# ---------------------------------------------------------------------------
# Job title extraction
# ---------------------------------------------------------------------------

def extract_job_title(text):
    """Extract job title from post text."""
    # Bold title pattern: **Org — Title** or **Title**
    patterns = [
        # "is hiring a Title" pattern
        r"is\s+hiring\s+(?:a|an)\s+\*?\*?([^*\n]+?)\*?\*?\s*(?:\n|$)",
        # "**Org — Title**"
        r"\*\*[^*]+?[-—–]\s*([^*]+?)\*\*",
        # "Hiring: Title" or "Role: Title"
        r"(?:Hiring|Role|Position|Opening)[:\s]+\*?\*?([^*\n]+?)\*?\*?(?:\s*at|\s*[-—–]|\n)",
        # Standalone bold: **Title**
        r"\*\*([^*]+?)\*\*",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            title = m.group(1).strip().rstrip(".,;:")
            # Skip poster names, org names, and generic words
            skip_words = ("Hiring", "Multiple Roles", "posted", "Reminder")
            if len(title) > 3 and not any(title.startswith(w) for w in skip_words):
                return title
    return None


# ---------------------------------------------------------------------------
# Multi-role post splitting
# ---------------------------------------------------------------------------

def split_multi_role_post(text, posted_date_str, org_name, base_deadline):
    """Split a multi-role post into individual role sections."""
    # Find numbered roles: "1. **Title** — details..."
    role_pattern = re.compile(
        r"\d+\.\s+\*\*([^*]+)\*\*\s*[-—–]?\s*(.*?)(?=\n\d+\.\s+\*\*|\nApply\b|\n---|\Z)",
        re.DOTALL,
    )
    roles = []
    for m in role_pattern.finditer(text):
        title = m.group(1).strip()
        details = m.group(2).strip()
        roles.append({"title": title, "details": details})
    return roles


# ---------------------------------------------------------------------------
# Tag inference
# ---------------------------------------------------------------------------

TAG_KEYWORDS = {
    "research": ["research", "researcher", "analyst"],
    "engineering": ["engineer", "engineering", "developer", "software", "web"],
    "operations": ["operations", "coordinator", "officer", "admin"],
    "communications": ["communications", "comms", "marketing", "writer"],
    "finance": ["finance", "financial", "accountant", "accounting"],
    "ai-safety": ["ai safety", "alignment", "interpretability"],
    "ai-governance": ["ai governance", "ai policy"],
    "animal-welfare": ["animal welfare", "animal rights", "farmed animal"],
    "global-health": ["global health", "malaria", "deworming", "givewell"],
    "climate": ["climate", "carbon", "emissions"],
    "grantmaking": ["grantmaking", "grant", "philanthropy"],
    "partnerships": ["partnerships", "partner"],
    "policy": ["policy", "government", "regulation"],
}


def infer_tags(title, text):
    """Infer tags from title and post text."""
    combined = f"{title} {text}".lower()
    tags = []
    for tag, keywords in TAG_KEYWORDS.items():
        for kw in keywords:
            # Use word boundary matching to avoid false positives
            # (e.g. "web" matching "Website")
            if re.search(r"\b" + re.escape(kw) + r"\b", combined):
                tags.append(tag)
                break
    return tags


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def compute_confidence(job_record, classification_confidence):
    """Compute a confidence score for a job record."""
    score = classification_confidence

    # Boost for successfully extracted fields
    if job_record.get("salary"):
        score = min(score + 0.05, 1.0)
    if job_record.get("source_url"):
        score = min(score + 0.05, 1.0)
    if job_record.get("deadline"):
        score = min(score + 0.02, 1.0)
    if job_record["location"].get("cities"):
        score = min(score + 0.03, 1.0)

    # Penalize for missing important fields
    if not job_record.get("salary"):
        score = max(score - 0.1, 0.0)
    if not job_record.get("source_url"):
        score = max(score - 0.1, 0.0)

    return round(score, 2)


# ---------------------------------------------------------------------------
# Post parsing
# ---------------------------------------------------------------------------

def split_posts(content):
    """Split Slack export markdown into individual posts."""
    # Split on horizontal rules and date headers
    posts = re.split(r"\n---\n", content)
    result = []
    for post in posts:
        post = post.strip()
        if not post:
            continue
        result.append(post)
    return result


def parse_posted_date(post_text):
    """Extract the section date header (## YYYY-MM-DD) from a post."""
    m = re.search(r"^##\s+(\d{4}-\d{2}-\d{2})", post_text, re.MULTILINE)
    if m:
        return m.group(1)
    return None


def parse_single_post(post_text):
    """Parse a single post into job and org records.

    Returns: (jobs_list, orgs_dict, classification)
    Each item in jobs_list is a job dict.
    orgs_dict maps org_id -> org_record.
    """
    classification, class_confidence = classify_post(post_text)
    if classification == "not_a_job":
        return [], {}, "not_a_job"

    posted_date = parse_posted_date(post_text)
    if not posted_date:
        # Try to extract from context
        posted_date = str(date.today())

    year_month = posted_date[:7]  # YYYY-MM
    urls = extract_urls(post_text)
    org_name = extract_org_name(post_text)

    if not org_name:
        return [], {}, "not_a_job"

    org_slug = slugify(org_name)
    org_record = build_org_record(org_name, post_text, urls)
    orgs = {org_slug: org_record}

    deadline = parse_deadline(post_text)
    jobs = []

    if classification == "multi_role_post":
        roles = split_multi_role_post(post_text, posted_date, org_name, deadline)
        for role in roles:
            title = role["title"]
            details = role["details"]
            title_slug = slugify(title)
            job_id = make_job_id(org_slug, title_slug, year_month)

            location = parse_location(details)
            salary = parse_salary(details)
            role_urls = extract_urls(details)
            apply_url = find_apply_url(role_urls) if role_urls else find_apply_url(urls)
            tags = infer_tags(title, details)

            today = str(date.today())
            job = {
                "id": job_id,
                "title": title,
                "organization": org_slug,
                "source": "slack-export",
                "source_url": apply_url,
                "jd_file": None,
                "location": location,
                "salary": salary,
                "posted_date": posted_date,
                "deadline": deadline,
                "date_added": today,
                "tags": tags,
                "status": "unknown",
                "confidence": 0.0,
                "notes": None,
            }
            job["confidence"] = compute_confidence(job, class_confidence)
            if job["confidence"] < 0.5:
                job["notes"] = "Low confidence: limited fields extracted from multi-role post"
            jobs.append(job)

    else:
        title = extract_job_title(post_text)
        if not title:
            return [], {}, "not_a_job"

        # Clean org name from title if present
        if org_name in title:
            title = title.replace(org_name, "").strip(" -—–")
        title = title.strip()
        if not title:
            return [], {}, "not_a_job"

        title_slug = slugify(title)
        job_id = make_job_id(org_slug, title_slug, year_month)

        location = parse_location(post_text)
        salary = parse_salary(post_text)
        apply_url = find_apply_url(urls)
        tags = infer_tags(title, post_text)

        today = str(date.today())
        job = {
            "id": job_id,
            "title": title,
            "organization": org_slug,
            "source": "slack-export",
            "source_url": apply_url,
            "jd_file": None,
            "location": location,
            "salary": salary,
            "posted_date": posted_date,
            "deadline": deadline,
            "date_added": today,
            "tags": tags,
            "status": "unknown",
            "confidence": 0.0,
            "notes": None,
        }
        job["confidence"] = compute_confidence(job, class_confidence)
        if job["confidence"] < 0.5:
            job["notes"] = "Low confidence: limited fields extracted from post"
        jobs.append(job)

    return jobs, orgs, classification


# ---------------------------------------------------------------------------
# Main parsing pipeline
# ---------------------------------------------------------------------------

def parse_export(export_path):
    """Parse the full Slack export file.

    Returns: (all_jobs, all_orgs, summary)
    """
    with open(export_path, "r", encoding="utf-8") as f:
        content = f.read()

    posts = split_posts(content)

    all_jobs = []
    all_orgs = {}
    stats = {
        "total_posts": len(posts),
        "jobs_found": 0,
        "orgs_found": 0,
        "skipped": 0,
        "low_confidence": 0,
    }

    for post in posts:
        jobs, orgs, classification = parse_single_post(post)

        if classification == "not_a_job":
            stats["skipped"] += 1
            continue

        all_jobs.extend(jobs)
        for org_id, org_record in orgs.items():
            if org_id in all_orgs:
                # Merge aliases
                existing = all_orgs[org_id]
                for alias in org_record.get("aliases", []):
                    if alias not in existing.get("aliases", []):
                        existing.setdefault("aliases", []).append(alias)
                # Merge cause areas
                for area in org_record.get("cause_areas", []):
                    if area not in existing.get("cause_areas", []):
                        existing.setdefault("cause_areas", []).append(area)
                # Update website if missing
                if not existing.get("website") and org_record.get("website"):
                    existing["website"] = org_record["website"]
            else:
                all_orgs[org_id] = org_record

    stats["jobs_found"] = len(all_jobs)
    stats["orgs_found"] = len(all_orgs)
    stats["low_confidence"] = sum(
        1 for j in all_jobs if j.get("confidence", 1.0) < 0.5
    )

    return all_jobs, all_orgs, stats


def write_outputs(all_jobs, all_orgs, stats):
    """Write job files, org files, and summary report."""
    # Ensure directories exist
    DATA_JOBS.mkdir(parents=True, exist_ok=True)
    DATA_ORGS.mkdir(parents=True, exist_ok=True)
    EXPORTS.mkdir(parents=True, exist_ok=True)

    # Write job files
    for job in all_jobs:
        path = DATA_JOBS / f"{job['id']}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(job, f, indent=2, ensure_ascii=False)
            f.write("\n")

    # Write org files (merge with existing if present)
    for org_id, org in all_orgs.items():
        path = DATA_ORGS / f"{org_id}.json"
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            # Merge: keep existing data, add new aliases and cause areas
            for alias in org.get("aliases", []):
                if alias not in existing.get("aliases", []):
                    existing.setdefault("aliases", []).append(alias)
            for area in org.get("cause_areas", []):
                if area not in existing.get("cause_areas", []):
                    existing.setdefault("cause_areas", []).append(area)
            # Fill in missing fields from new data
            if not existing.get("website") and org.get("website"):
                existing["website"] = org["website"]
            if not existing.get("hq_location") and org.get("hq_location"):
                existing["hq_location"] = org["hq_location"]
            org = existing
        with open(path, "w", encoding="utf-8") as f:
            json.dump(org, f, indent=2, ensure_ascii=False)
            f.write("\n")

    # Write summary report
    report_path = EXPORTS / "slack-export-summary.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("EA Slack Export Parse Summary\n")
        f.write("=" * 40 + "\n\n")
        f.write(f"Total posts processed: {stats['total_posts']}\n")
        f.write(f"Jobs found: {stats['jobs_found']}\n")
        f.write(f"Organizations found: {stats['orgs_found']}\n")
        f.write(f"Posts skipped (not jobs): {stats['skipped']}\n")
        f.write(f"Low-confidence records: {stats['low_confidence']}\n")

    return report_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    if argv is None:
        argv = sys.argv

    export_path = get_export_path(argv)
    if not export_path:
        print(
            "ERROR: Slack export path not configured.\n"
            "Set one of:\n"
            "  1. Pass path as CLI argument: python3 scripts/parse_slack_export.py /path/to/export.md\n"
            "  2. Set EA_SLACK_EXPORT_PATH environment variable\n"
            "  3. Add slack_export_path to config.json at repo root",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.path.isfile(export_path):
        print(f"ERROR: Slack export file not found: {export_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing Slack export: {export_path}")
    all_jobs, all_orgs, stats = parse_export(export_path)
    report_path = write_outputs(all_jobs, all_orgs, stats)

    print(f"\nDone!")
    print(f"  Jobs: {stats['jobs_found']}")
    print(f"  Orgs: {stats['orgs_found']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Low-confidence: {stats['low_confidence']}")
    print(f"  Report: {report_path}")


if __name__ == "__main__":
    main()
