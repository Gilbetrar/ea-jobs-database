#!/usr/bin/env python3
"""Fetch job descriptions from source URLs and save as markdown.

Two workflows:

1. Incremental fetch (default):
   python3 scripts/fetch_jds.py [--limit N] [--dry-run]
   Fetches JDs that don't already have files, writes to data/jds/

2. Full re-fetch pipeline (Issue #8):
   python3 scripts/fetch_jds.py --overwrite [--dry-run] [--limit N]
   Fetches ALL JDs to data/jds-staging/ (even if already cached)

3. Promote from staging:
   python3 scripts/fetch_jds.py --promote
   Scores staged files, backs up production, promotes passing files

4. Full pipeline:
   python3 scripts/fetch_jds.py --overwrite --promote [--dry-run] [--limit N]
   Fetch to staging, then score/backup/promote/report
"""

import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

# Project root is one level up from scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_JOBS = PROJECT_ROOT / "data" / "jobs"
DATA_ORGS = PROJECT_ROOT / "data" / "orgs"
DATA_JDS = PROJECT_ROOT / "data" / "jds"
DATA_JDS_STAGING = PROJECT_ROOT / "data" / "jds-staging"
DATA_JDS_BACKUP = PROJECT_ROOT / "data" / "jds-backup"
EXPORTS = PROJECT_ROOT / "exports"

# Minimum delay between requests to the same domain (seconds)
RATE_LIMIT_DELAY = 1.5
MAX_REDIRECTS = 3
REQUEST_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Skip list -- application forms, not JDs
# ---------------------------------------------------------------------------

FORM_PATTERNS = [
    "docs.google.com/forms",
    "typeform.com",
    "airtable.com/app",
    "surveymonkey.com",
    "jotform.com",
]


def is_form_url(url):
    """Return True if URL is an application form (not a JD)."""
    if not url:
        return False
    url_lower = url.lower()
    return any(pattern in url_lower for pattern in FORM_PATTERNS)


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def detect_platform(url):
    """Detect the job platform from URL."""
    if not url:
        return "unknown"
    url_lower = url.lower()
    if "jobs.lever.co" in url_lower or "lever.co" in url_lower:
        return "lever"
    if "jobs.ashbyhq.com" in url_lower or "ashbyhq.com" in url_lower:
        return "ashby"
    if "boards.greenhouse.io" in url_lower or "greenhouse.io" in url_lower:
        return "greenhouse"
    if "docs.google.com/document" in url_lower:
        return "google-docs"
    if "apply.workable.com" in url_lower or "workable.com" in url_lower:
        return "workable"
    return "generic"


# ---------------------------------------------------------------------------
# HTML to Markdown conversion
# ---------------------------------------------------------------------------

class HTMLToMarkdown(HTMLParser):
    """Simple HTML to Markdown converter focused on JD content."""

    def __init__(self):
        super().__init__()
        self.output = []
        self.current_tag = None
        self.tag_stack = []
        self.list_type_stack = []  # 'ul' or 'ol'
        self.list_counter_stack = []
        self.in_pre = False
        self.skip = False
        self.skip_tags = {"script", "style", "nav", "footer", "header", "noscript"}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self.tag_stack.append(tag)
        self.current_tag = tag

        if tag in self.skip_tags:
            self.skip = True
            return

        attrs_dict = dict(attrs)

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self.output.append("\n" + "#" * level + " ")
        elif tag == "p":
            self.output.append("\n\n")
        elif tag == "br":
            self.output.append("\n")
        elif tag == "ul":
            self.list_type_stack.append("ul")
            self.list_counter_stack.append(0)
            self.output.append("\n")
        elif tag == "ol":
            self.list_type_stack.append("ol")
            self.list_counter_stack.append(0)
            self.output.append("\n")
        elif tag == "li":
            indent = "  " * max(0, len(self.list_type_stack) - 1)
            if self.list_type_stack and self.list_type_stack[-1] == "ol":
                self.list_counter_stack[-1] += 1
                self.output.append(f"\n{indent}{self.list_counter_stack[-1]}. ")
            else:
                self.output.append(f"\n{indent}- ")
        elif tag == "a":
            href = attrs_dict.get("href", "")
            self.output.append("[")
            self._pending_href = href
        elif tag == "strong" or tag == "b":
            self.output.append("**")
        elif tag == "em" or tag == "i":
            self.output.append("*")
        elif tag == "pre":
            self.in_pre = True
            self.output.append("\n```\n")
        elif tag == "code" and not self.in_pre:
            self.output.append("`")
        elif tag == "div":
            self.output.append("\n")
        elif tag == "hr":
            self.output.append("\n---\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.tag_stack and self.tag_stack[-1] == tag:
            self.tag_stack.pop()

        if tag in self.skip_tags:
            self.skip = False
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.output.append("\n")
        elif tag == "p":
            self.output.append("\n")
        elif tag == "a":
            href = getattr(self, "_pending_href", "")
            self.output.append(f"]({href})")
            self._pending_href = ""
        elif tag == "strong" or tag == "b":
            self.output.append("**")
        elif tag == "em" or tag == "i":
            self.output.append("*")
        elif tag == "pre":
            self.in_pre = False
            self.output.append("\n```\n")
        elif tag == "code" and not self.in_pre:
            self.output.append("`")
        elif tag == "ul" or tag == "ol":
            if self.list_type_stack:
                self.list_type_stack.pop()
            if self.list_counter_stack:
                self.list_counter_stack.pop()
            self.output.append("\n")
        elif tag == "li":
            pass  # newline added at start of next li

        self.current_tag = self.tag_stack[-1] if self.tag_stack else None

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_pre:
            self.output.append(data)
        else:
            # Collapse whitespace in normal flow
            text = re.sub(r'\s+', ' ', data)
            self.output.append(text)

    def get_markdown(self):
        md = "".join(self.output)
        # Clean up excessive blank lines
        md = re.sub(r'\n{3,}', '\n\n', md)
        return md.strip()


def html_to_markdown(html_content):
    """Convert HTML to clean markdown."""
    parser = HTMLToMarkdown()
    parser.feed(html_content)
    return parser.get_markdown()


# ---------------------------------------------------------------------------
# Platform-specific extractors
# ---------------------------------------------------------------------------

def extract_lever(html):
    """Extract JD content from Lever job page HTML.

    Lever pages have large inline CSS that contains class names like 'posting-page'
    and 'content'. We strip everything before the last </style> tag to avoid
    matching CSS selectors instead of actual content.
    """
    # Strip CSS/head to avoid matching class names in stylesheets
    style_end = html.rfind('</style>')
    body_html = html[style_end:] if style_end > 0 else html

    content = _extract_between_markers(
        body_html,
        [r'class="section page-centered posting-header"',
         r'class="posting-headline"',
         r'class="posting-page"'],
        [r'class="section page-centered last-section-apply"',
         r'class="posting-btn-submit"',
         r'<div class="postings-btn']
    )
    if content:
        return html_to_markdown(content)
    return _extract_body(html)


def extract_ashby(html):
    """Extract JD content from Ashby job page HTML."""
    content = _extract_between_markers(
        html,
        [r'class="ashby-job-posting-brief-description"', r'class="ashby-job-posting"',
         r'data-testid="job-posting"'],
        [r'class="ashby-job-posting-apply"', r'<footer', r'</main>']
    )
    if content:
        return html_to_markdown(content)
    return _extract_body(html)


def extract_greenhouse(html):
    """Extract JD content from Greenhouse job page HTML."""
    content = _extract_between_markers(
        html,
        [r'id="content"', r'id="app_body"', r'class="job-post'],
        [r'id="application"', r'<form', r'</main>']
    )
    if content:
        return html_to_markdown(content)
    return _extract_body(html)


def extract_workable(html):
    """Extract JD content from Workable job page HTML.

    Workable is often JS-rendered, similar to Ashby.
    """
    content = _extract_between_markers(
        html,
        [r'class="job-description"', r'class="job-details"',
         r'data-ui="job-description"', r'<article'],
        [r'class="application-form"', r'id="application"', r'<footer', r'</main>']
    )
    if content:
        return html_to_markdown(content)
    return _extract_body(html)


def extract_generic(html):
    """Extract JD content from a generic webpage."""
    content = _extract_between_markers(
        html,
        [r'<article', r'<main', r'class="content"', r'class="job-description"',
         r'class="entry-content"', r'role="main"'],
        [r'</article>', r'</main>', r'<footer']
    )
    if content:
        return html_to_markdown(content)
    return _extract_body(html)


def _extract_between_markers(html, start_patterns, end_patterns):
    """Extract HTML content between the first matching start and end pattern."""
    start_pos = None
    for pattern in start_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            close_bracket = html.find(">", match.end())
            if close_bracket != -1:
                start_pos = close_bracket + 1
            else:
                start_pos = match.end()
            break

    if start_pos is None:
        return None

    end_pos = None
    for pattern in end_patterns:
        match = re.search(pattern, html[start_pos:], re.IGNORECASE)
        if match:
            end_pos = start_pos + match.start()
            break

    if end_pos is None:
        end_pos = len(html)

    return html[start_pos:end_pos]


def _extract_body(html):
    """Fallback: extract the body content."""
    body_match = re.search(r'<body[^>]*>(.*)</body>', html, re.DOTALL | re.IGNORECASE)
    if body_match:
        return html_to_markdown(body_match.group(1))
    return html_to_markdown(html)


PLATFORM_EXTRACTORS = {
    "lever": extract_lever,
    "ashby": extract_ashby,
    "greenhouse": extract_greenhouse,
    "workable": extract_workable,
    "generic": extract_generic,
    "google-docs": extract_generic,
}


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

_domain_last_request = {}


def _rate_limit(url):
    """Enforce rate limiting per domain."""
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc
    now = time.time()
    last = _domain_last_request.get(domain, 0)
    wait = RATE_LIMIT_DELAY - (now - last)
    if wait > 0:
        time.sleep(wait)
    _domain_last_request[domain] = time.time()


def fetch_url(url):
    """Fetch URL content with redirect following and error handling.

    Returns (html_content, final_url, error_message).
    """
    if not url:
        return None, None, "No URL provided"

    current_url = url
    for _ in range(MAX_REDIRECTS):
        _rate_limit(current_url)
        try:
            req = urllib.request.Request(
                current_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (ea-jobs-database JD archiver)",
                    "Accept": "text/html,application/xhtml+xml,*/*",
                }
            )
            response = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
            content = response.read().decode("utf-8", errors="replace")
            return content, current_url, None
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 307, 308):
                redirect_url = e.headers.get("Location")
                if redirect_url:
                    current_url = urllib.parse.urljoin(current_url, redirect_url)
                    continue
            return None, current_url, f"HTTP {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return None, current_url, f"URL error: {e.reason}"
        except Exception as e:
            return None, current_url, f"Fetch error: {str(e)}"

    return None, current_url, f"Too many redirects (>{MAX_REDIRECTS})"


def build_frontmatter(job_id, source_url, platform):
    """Build YAML frontmatter for a JD markdown file."""
    return (
        f"---\n"
        f"job_id: {job_id}\n"
        f"source_url: {source_url}\n"
        f"fetched_date: {date.today().isoformat()}\n"
        f"platform: {platform}\n"
        f"---\n\n"
    )


def extract_jd_content(html, platform, job_title=None):
    """Extract JD markdown content from HTML using platform-specific extractor."""
    extractor = PLATFORM_EXTRACTORS.get(platform, extract_generic)
    content = extractor(html)

    if job_title and content and not content.startswith("#"):
        content = f"# {job_title}\n\n{content}"

    return content


# ---------------------------------------------------------------------------
# Job loading
# ---------------------------------------------------------------------------

def load_job_records():
    """Load all job JSON files from data/jobs/."""
    jobs = []
    for filepath in sorted(DATA_JOBS.glob("*.json")):
        if filepath.name == ".gitkeep":
            continue
        with open(filepath) as f:
            job = json.load(f)
        job["_filepath"] = str(filepath)
        jobs.append(job)
    return jobs


# ---------------------------------------------------------------------------
# Original incremental fetch (writes to data/jds/)
# ---------------------------------------------------------------------------

def process_jobs(jobs, dry_run=False, limit=None):
    """Process job records: fetch JDs and save as markdown to data/jds/.

    Returns a summary dict with counts. Used for incremental mode.
    """
    summary = {
        "total_urls": 0,
        "fetched": 0,
        "skipped_forms": 0,
        "skipped_no_url": 0,
        "skipped_cached": 0,
        "failed_dead": 0,
        "errors": [],
    }

    processed = 0
    for job in jobs:
        if limit and processed >= limit:
            break

        job_id = job.get("id", "unknown")
        source_url = job.get("source_url")
        jd_file_path = DATA_JDS / f"{job_id}.md"

        if not source_url:
            summary["skipped_no_url"] += 1
            continue

        summary["total_urls"] += 1

        if is_form_url(source_url):
            summary["skipped_forms"] += 1
            print(f"  SKIP (form): {job_id} -- {source_url}", file=sys.stderr)
            continue

        if jd_file_path.exists():
            summary["skipped_cached"] += 1
            continue

        if dry_run:
            print(f"  DRY-RUN: would fetch {job_id} -- {source_url}", file=sys.stderr)
            continue

        platform = detect_platform(source_url)
        print(f"  FETCH [{platform}]: {job_id} -- {source_url}", file=sys.stderr)

        html, final_url, error = fetch_url(source_url)

        if error:
            summary["failed_dead"] += 1
            summary["errors"].append({"job_id": job_id, "url": source_url, "error": error})
            print(f"    FAIL: {error}", file=sys.stderr)
            _update_job_record(job, jd_status="dead_link")
            continue

        content = extract_jd_content(html, platform, job.get("title"))
        if not content or len(content.strip()) < 50:
            summary["failed_dead"] += 1
            summary["errors"].append({
                "job_id": job_id, "url": source_url,
                "error": "Extracted content too short or empty"
            })
            print(f"    FAIL: Content too short/empty", file=sys.stderr)
            _update_job_record(job, jd_status="extraction_failed")
            continue

        frontmatter = build_frontmatter(job_id, source_url, platform)
        full_md = frontmatter + content

        jd_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(jd_file_path, "w") as f:
            f.write(full_md)

        _update_job_record(job, jd_file=f"data/jds/{job_id}.md")

        summary["fetched"] += 1
        processed += 1
        print(f"    OK: saved {jd_file_path.name}", file=sys.stderr)

    return summary


# ---------------------------------------------------------------------------
# Staging fetch (--overwrite mode, writes to data/jds-staging/)
# ---------------------------------------------------------------------------

def fetch_to_staging(jobs, dry_run=False, limit=None):
    """Fetch ALL JDs to staging directory, even if already cached.

    Returns a summary dict with per-platform breakdowns.
    """
    if not dry_run:
        DATA_JDS_STAGING.mkdir(parents=True, exist_ok=True)

    summary = {
        "total": len(jobs),
        "fetchable": 0,
        "fetched": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "by_platform": defaultdict(lambda: {
            "attempted": 0, "fetched": 0, "failed": 0,
            "failed_reasons": defaultdict(int),
        }),
        "fatal_signals": [],
    }

    processed = 0
    for job in jobs:
        if limit and processed >= limit:
            break

        job_id = job.get("id", "unknown")
        source_url = job.get("source_url")

        if not source_url:
            summary["skipped"] += 1
            continue

        if is_form_url(source_url):
            summary["skipped"] += 1
            print(f"  SKIP (form): {job_id}", file=sys.stderr)
            continue

        summary["fetchable"] += 1
        platform = detect_platform(source_url)
        summary["by_platform"][platform]["attempted"] += 1

        staging_path = DATA_JDS_STAGING / f"{job_id}.md"

        if dry_run:
            print(f"  DRY-RUN: would fetch {job_id} [{platform}]", file=sys.stderr)
            processed += 1
            continue

        print(f"  FETCH [{platform}]: {job_id} -- {source_url}", file=sys.stderr)

        html, final_url, error = fetch_url(source_url)

        if error:
            summary["failed"] += 1
            summary["by_platform"][platform]["failed"] += 1
            reason = _classify_error(error)
            summary["by_platform"][platform]["failed_reasons"][reason] += 1
            summary["errors"].append({
                "job_id": job_id, "url": source_url, "error": error,
                "platform": platform, "reason": reason,
            })
            print(f"    FAIL: {error}", file=sys.stderr)
            processed += 1
            continue

        content = extract_jd_content(html, platform, job.get("title"))
        if not content or len(content.strip()) < 50:
            summary["failed"] += 1
            summary["by_platform"][platform]["failed"] += 1
            summary["by_platform"][platform]["failed_reasons"]["extraction_failed"] += 1
            summary["errors"].append({
                "job_id": job_id, "url": source_url,
                "error": "Extracted content too short or empty",
                "platform": platform, "reason": "extraction_failed",
            })
            print(f"    FAIL: Content too short/empty", file=sys.stderr)
            processed += 1
            continue

        frontmatter = build_frontmatter(job_id, source_url, platform)
        full_md = frontmatter + content

        with open(staging_path, "w") as f:
            f.write(full_md)

        summary["fetched"] += 1
        summary["by_platform"][platform]["fetched"] += 1
        processed += 1
        print(f"    OK: staged {staging_path.name}", file=sys.stderr)

    return summary


def _classify_error(error_msg):
    """Classify an error message into a reason category."""
    error_lower = error_msg.lower()
    if "404" in error_lower or "not found" in error_lower:
        return "http_404"
    if "403" in error_lower or "forbidden" in error_lower:
        return "http_403"
    if "timeout" in error_lower:
        return "timeout"
    if "ssl" in error_lower or "certificate" in error_lower:
        return "ssl_error"
    if "redirect" in error_lower:
        return "too_many_redirects"
    if "http" in error_lower:
        return "http_error"
    return "other"


# ---------------------------------------------------------------------------
# Backup, scoring, promotion pipeline
# ---------------------------------------------------------------------------

def backup_production():
    """One-time idempotent backup of data/jds/ to data/jds-backup/.

    If backup already exists, skip.
    """
    if DATA_JDS_BACKUP.exists():
        count = len(list(DATA_JDS_BACKUP.glob("*.md")))
        print(f"  Backup already exists ({count} files), skipping.", file=sys.stderr)
        return False

    print(f"  Backing up data/jds/ to data/jds-backup/...", file=sys.stderr)
    shutil.copytree(DATA_JDS, DATA_JDS_BACKUP)
    count = len(list(DATA_JDS_BACKUP.glob("*.md")))
    print(f"  Backed up {count} files.", file=sys.stderr)
    return True


def score_staged_files():
    """Score all files in staging dir using jd_quality.py.

    Returns a list of dicts with scoring results.
    """
    # Import scorer (same package)
    from jd_quality import score_jd, strip_frontmatter

    results = []
    staged_files = sorted(DATA_JDS_STAGING.glob("*.md"))
    print(f"  Scoring {len(staged_files)} staged files...", file=sys.stderr)

    for filepath in staged_files:
        with open(filepath) as f:
            content = f.read()

        # Extract platform from frontmatter
        platform = "generic"
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                fm = content[3:end]
                for line in fm.split("\n"):
                    if line.startswith("platform:"):
                        platform = line.split(":", 1)[1].strip()
                        break

        # Extract job_id from frontmatter
        job_id = filepath.stem
        source_url = ""
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                fm = content[3:end]
                for line in fm.split("\n"):
                    if line.startswith("source_url:"):
                        source_url = line.split(":", 1)[1].strip()
                        break

        score = score_jd(content, platform)
        body = strip_frontmatter(content)

        results.append({
            "job_id": job_id,
            "platform": platform,
            "source_url": source_url,
            "staging_path": str(filepath),
            "score": score.total,
            "tier": score.tier,
            "fatal_signal": score.fatal_signal,
            "length_score": score.length_score,
            "structure_score": score.structure_score,
            "vocabulary_score": score.vocabulary_score,
            "platform_score": score.platform_score,
            "encoding_score": score.encoding_score,
            "negative_penalty": score.negative_penalty,
            "body_length": len(body),
            "preview": body[:200].replace("\n", " "),
        })

    return results


def triage_results(scored_results):
    """Triage scored results into promote/review/quarantine.

    Returns (promoted, review_queue, quarantined).
    """
    promoted = []
    review_candidates = []
    quarantined = []

    for r in scored_results:
        if r["tier"] == "promote":
            promoted.append(r)
        elif r["tier"] == "review":
            review_candidates.append(r)
        else:
            quarantined.append(r)

    # Build the review queue (target 20-50 items)
    review_queue = []

    # All borderline items (score 35-45)
    borderline = [r for r in scored_results if 35 <= r["score"] <= 45]
    review_queue.extend(borderline)

    # At least 2 items per platform that has review items
    platform_review = defaultdict(list)
    for r in review_candidates:
        platform_review[r["platform"]].append(r)
    for platform, items in platform_review.items():
        already_in = [r for r in review_queue if r["platform"] == platform]
        needed = max(0, 2 - len(already_in))
        remaining = [r for r in items if r not in review_queue]
        review_queue.extend(remaining[:needed])

    # 5 shortest auto-promoted JDs (most likely false positives)
    promoted_by_length = sorted(promoted, key=lambda r: r["body_length"])
    for r in promoted_by_length[:5]:
        if r not in review_queue:
            review_queue.append(r)

    # 3 highest-scoring quarantined items (most likely false negatives)
    quarantined_by_score = sorted(quarantined, key=lambda r: r["score"], reverse=True)
    for r in quarantined_by_score[:3]:
        if r not in review_queue:
            review_queue.append(r)

    return promoted, review_queue, quarantined


def promote_files(promoted, dry_run=False):
    """Copy promoted files from staging to production.

    Only overwrites if the staged file is longer than the existing production file.
    """
    count = 0
    skipped = 0
    for r in promoted:
        staging_path = Path(r["staging_path"])
        prod_path = DATA_JDS / staging_path.name

        if not staging_path.exists():
            continue

        # Read staged content
        staged_content = staging_path.read_text()

        # Check if production file exists and compare lengths
        if prod_path.exists():
            prod_content = prod_path.read_text()
            # Only promote if staged is longer (better content)
            from jd_quality import strip_frontmatter
            staged_body = strip_frontmatter(staged_content)
            prod_body = strip_frontmatter(prod_content)
            if len(staged_body) <= len(prod_body):
                skipped += 1
                continue

        if dry_run:
            print(f"  DRY-RUN: would promote {staging_path.name}", file=sys.stderr)
            count += 1
            continue

        with open(prod_path, "w") as f:
            f.write(staged_content)
        count += 1

    print(f"  Promoted {count} files, skipped {skipped} (not longer).", file=sys.stderr)
    return count


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_refetch_report(fetch_summary, promoted, quarantined, review_queue):
    """Generate exports/jd_refetch_report.json with full pipeline results."""
    EXPORTS.mkdir(parents=True, exist_ok=True)

    # Merge platform data with promotion info
    by_platform = {}
    for platform, data in fetch_summary.get("by_platform", {}).items():
        platform_promoted = [r for r in promoted if r["platform"] == platform]
        platform_quarantined = [r for r in quarantined if r["platform"] == platform]
        platform_review = [r for r in review_queue if r["platform"] == platform]
        by_platform[platform] = {
            "attempted": data["attempted"],
            "fetched": data["fetched"],
            "promoted": len(platform_promoted),
            "quarantined": len(platform_quarantined),
            "review": len(platform_review),
            "failed": data["failed"],
            "failed_reasons": dict(data.get("failed_reasons", {})),
        }

    # Collect fatal signals
    fatal_signals = []
    for r in quarantined:
        if r.get("fatal_signal"):
            fatal_signals.append({
                "job_id": r["job_id"],
                "url": r.get("source_url", ""),
                "signal": r["fatal_signal"],
                "platform": r["platform"],
            })

    report = {
        "total": fetch_summary.get("total", 0),
        "fetchable": fetch_summary.get("fetchable", 0),
        "fetched": fetch_summary.get("fetched", 0),
        "failed": fetch_summary.get("failed", 0),
        "skipped": fetch_summary.get("skipped", 0),
        "promoted": len(promoted),
        "quarantined": len(quarantined),
        "review_queue": len(review_queue),
        "by_platform": by_platform,
        "fatal_signals": fatal_signals,
    }

    report_path = EXPORTS / "jd_refetch_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    print(f"  Refetch report: {report_path}", file=sys.stderr)
    return report


def generate_quarantine_manifest(quarantined):
    """Generate exports/jd_quarantine.json."""
    EXPORTS.mkdir(parents=True, exist_ok=True)

    manifest = []
    for r in quarantined:
        manifest.append({
            "job_id": r["job_id"],
            "platform": r["platform"],
            "source_url": r.get("source_url", ""),
            "score": r["score"],
            "fatal_signal": r.get("fatal_signal"),
            "body_length": r["body_length"],
            "reason": r.get("fatal_signal") or f"score_{r['score']}",
        })

    path = EXPORTS / "jd_quarantine.json"
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    print(f"  Quarantine manifest: {path} ({len(manifest)} items)", file=sys.stderr)
    return manifest


def generate_review_queue(review_queue):
    """Generate exports/jd_review_queue.md and .json."""
    EXPORTS.mkdir(parents=True, exist_ok=True)

    # JSON version
    json_path = EXPORTS / "jd_review_queue.json"
    json_items = []
    for r in review_queue:
        json_items.append({
            "job_id": r["job_id"],
            "platform": r["platform"],
            "source_url": r.get("source_url", ""),
            "score": r["score"],
            "tier": r["tier"],
            "body_length": r["body_length"],
            "score_breakdown": {
                "length": r["length_score"],
                "structure": r["structure_score"],
                "vocabulary": r["vocabulary_score"],
                "platform": r["platform_score"],
                "encoding": r["encoding_score"],
                "negative": -r["negative_penalty"],
            },
            "preview": r["preview"],
        })
    with open(json_path, "w") as f:
        json.dump(json_items, f, indent=2)
        f.write("\n")

    # Markdown version
    md_lines = [
        "# JD Review Queue",
        "",
        f"Generated: {date.today().isoformat()}",
        f"Total items: {len(review_queue)}",
        "",
        "---",
        "",
    ]
    for r in sorted(review_queue, key=lambda x: x["score"]):
        md_lines.extend([
            f"## {r['job_id']}",
            "",
            f"- **Platform**: {r['platform']}",
            f"- **Score**: {r['score']} ({r['tier']})",
            f"- **Body length**: {r['body_length']} chars",
            f"- **URL**: {r.get('source_url', 'N/A')}",
            f"- **Breakdown**: L={r['length_score']} S={r['structure_score']} "
            f"V={r['vocabulary_score']} P={r['platform_score']} "
            f"E={r['encoding_score']} N=-{r['negative_penalty']}",
            "",
            f"**Preview**: {r['preview'][:200]}",
            "",
            "---",
            "",
        ])

    md_path = EXPORTS / "jd_review_queue.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))

    print(f"  Review queue: {md_path} ({len(review_queue)} items)", file=sys.stderr)
    return json_items


# ---------------------------------------------------------------------------
# Job record updates
# ---------------------------------------------------------------------------

def _update_job_record(job, **updates):
    """Update a job JSON file with new fields."""
    filepath = job.get("_filepath")
    if not filepath:
        return

    with open(filepath) as f:
        data = json.load(f)

    data.update(updates)

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Legacy summary report (incremental mode)
# ---------------------------------------------------------------------------

def write_summary_report(summary):
    """Write a summary report to exports/ (incremental mode)."""
    EXPORTS.mkdir(parents=True, exist_ok=True)
    report_path = EXPORTS / "jd_fetch_summary.txt"

    lines = [
        "JD Fetch Summary Report",
        "=" * 40,
        f"Date: {date.today().isoformat()}",
        "",
        f"Total URLs found: {summary['total_urls']}",
        f"Fetched: {summary['fetched']}",
        f"Skipped (forms): {summary['skipped_forms']}",
        f"Skipped (no URL): {summary['skipped_no_url']}",
        f"Skipped (already cached): {summary['skipped_cached']}",
        f"Failed (dead links): {summary['failed_dead']}",
        "",
    ]

    if summary["errors"]:
        lines.append("Errors:")
        for err in summary["errors"]:
            lines.append(f"  - {err['job_id']}: {err['error']}")
            lines.append(f"    URL: {err['url']}")
        lines.append("")

    report_content = "\n".join(lines) + "\n"

    with open(report_path, "w") as f:
        f.write(report_content)

    print(f"\nSummary report written to: {report_path}", file=sys.stderr)
    return report_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    """Main entry point."""
    if argv is None:
        argv = sys.argv

    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0

    dry_run = "--dry-run" in argv
    overwrite = "--overwrite" in argv
    promote_flag = "--promote" in argv
    promote_only = "--promote-only" in argv
    limit = None
    if "--limit" in argv:
        idx = argv.index("--limit")
        if idx + 1 < len(argv):
            limit = int(argv[idx + 1])

    print("EA Jobs Database -- JD Fetcher", file=sys.stderr)
    print("=" * 40, file=sys.stderr)

    jobs = load_job_records()
    print(f"Found {len(jobs)} job records", file=sys.stderr)

    if not jobs:
        print("No job records found in data/jobs/. Run the parser first.", file=sys.stderr)
        return 0

    # Mode: promote-only (skip fetching, just score/promote existing staging)
    if promote_only:
        if not DATA_JDS_STAGING.exists():
            print("ERROR: data/jds-staging/ does not exist. Run with --overwrite first.",
                  file=sys.stderr)
            return 1

        print("\n--- Scoring staged files ---", file=sys.stderr)
        scored = score_staged_files()
        promoted, review_queue, quarantined = triage_results(scored)
        print(f"  Triage: {len(promoted)} promote, {len(review_queue)} review, "
              f"{len(quarantined)} quarantine", file=sys.stderr)

        print("\n--- Backing up production ---", file=sys.stderr)
        backup_production()

        print("\n--- Promoting passing files ---", file=sys.stderr)
        promote_files(promoted, dry_run=dry_run)

        print("\n--- Generating reports ---", file=sys.stderr)
        # Build a minimal fetch summary for the report
        fetch_summary = {
            "total": len(jobs),
            "fetchable": len(scored),
            "fetched": len(scored),
            "failed": 0,
            "skipped": len(jobs) - len(scored),
            "by_platform": _build_platform_summary_from_scored(scored),
        }
        generate_refetch_report(fetch_summary, promoted, quarantined, review_queue)
        generate_quarantine_manifest(quarantined)
        generate_review_queue(review_queue)

        print(f"\nDone: {len(promoted)} promoted, {len(quarantined)} quarantined, "
              f"{len(review_queue)} for review", file=sys.stderr)
        return 0

    # Mode: overwrite (fetch to staging, optionally promote)
    if overwrite:
        print(f"\n--- Fetching to staging (overwrite mode) ---", file=sys.stderr)
        fetch_summary = fetch_to_staging(jobs, dry_run=dry_run, limit=limit)

        if dry_run:
            print(f"\nDry run complete. Would fetch {fetch_summary['fetchable']} JDs.",
                  file=sys.stderr)
            return 0

        print(f"\nFetch complete: {fetch_summary['fetched']} fetched, "
              f"{fetch_summary['failed']} failed, "
              f"{fetch_summary['skipped']} skipped", file=sys.stderr)

        if promote_flag:
            print("\n--- Scoring staged files ---", file=sys.stderr)
            scored = score_staged_files()
            promoted, review_queue, quarantined = triage_results(scored)
            print(f"  Triage: {len(promoted)} promote, {len(review_queue)} review, "
                  f"{len(quarantined)} quarantine", file=sys.stderr)

            print("\n--- Backing up production ---", file=sys.stderr)
            backup_production()

            print("\n--- Promoting passing files ---", file=sys.stderr)
            promote_files(promoted, dry_run=dry_run)

            print("\n--- Generating reports ---", file=sys.stderr)
            generate_refetch_report(fetch_summary, promoted, quarantined, review_queue)
            generate_quarantine_manifest(quarantined)
            generate_review_queue(review_queue)

            print(f"\nPipeline complete: {len(promoted)} promoted, "
                  f"{len(quarantined)} quarantined, {len(review_queue)} for review",
                  file=sys.stderr)
        else:
            print("\nTo score and promote staged files, run with --promote-only",
                  file=sys.stderr)

        return 0

    # Default: incremental fetch (original behavior)
    summary = process_jobs(jobs, dry_run=dry_run, limit=limit)
    write_summary_report(summary)
    print(f"\nDone: {summary['fetched']} fetched, "
          f"{summary['skipped_forms']} forms skipped, "
          f"{summary['failed_dead']} failed", file=sys.stderr)

    return 0


def _build_platform_summary_from_scored(scored_results):
    """Build platform summary dict from scored results (for promote-only mode)."""
    by_platform = defaultdict(lambda: {
        "attempted": 0, "fetched": 0, "failed": 0,
        "failed_reasons": {},
    })
    for r in scored_results:
        by_platform[r["platform"]]["attempted"] += 1
        by_platform[r["platform"]]["fetched"] += 1
    return dict(by_platform)


if __name__ == "__main__":
    sys.exit(main())
