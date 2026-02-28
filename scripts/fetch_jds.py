#!/usr/bin/env python3
"""Fetch job descriptions from source URLs and save as markdown in data/jds/.

Usage:
    python3 scripts/fetch_jds.py [--dry-run] [--limit N]

Scans all job JSON files in data/jobs/ for source_url fields, fetches each URL,
converts the JD content to clean markdown, and saves to data/jds/{job-id}.md.
"""

import glob
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

# Project root is one level up from scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_JOBS = PROJECT_ROOT / "data" / "jobs"
DATA_ORGS = PROJECT_ROOT / "data" / "orgs"
DATA_JDS = PROJECT_ROOT / "data" / "jds"
EXPORTS = PROJECT_ROOT / "exports"

# Minimum delay between requests to the same domain (seconds)
RATE_LIMIT_DELAY = 1.5
MAX_REDIRECTS = 3
REQUEST_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Skip list — application forms, not JDs
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
    """Extract JD content from Lever job page HTML."""
    # Lever uses .posting-headline, .posting-categories, and content sections
    # Try to extract the main posting content
    content = _extract_between_markers(
        html,
        [r'class="posting-page"', r'class="content"', r'<div class="posting-'],
        [r'class="posting-btn-submit"', r'<div class="postings-btn', r'</main>']
    )
    if content:
        return html_to_markdown(content)
    # Fallback: extract body content
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


def extract_generic(html):
    """Extract JD content from a generic webpage."""
    # Try common content containers
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
    """Extract HTML content between the first matching start and end pattern.

    Starts extraction after the closing '>' of the matched start tag.
    """
    start_pos = None
    for pattern in start_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            # Find the closing '>' of the tag containing this attribute/pattern
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
    "generic": extract_generic,
    "google-docs": extract_generic,
}


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

# Track last request time per domain for rate limiting
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
            # Check for meta refresh or JS redirect
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

    # If we have a job title and the content doesn't start with a heading, add one
    if job_title and content and not content.startswith("#"):
        content = f"# {job_title}\n\n{content}"

    return content


# ---------------------------------------------------------------------------
# Main processing
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


def process_jobs(jobs, dry_run=False, limit=None):
    """Process job records: fetch JDs and save as markdown.

    Returns a summary dict with counts.
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

        # Skip if no URL
        if not source_url:
            summary["skipped_no_url"] += 1
            continue

        summary["total_urls"] += 1

        # Skip form URLs
        if is_form_url(source_url):
            summary["skipped_forms"] += 1
            print(f"  SKIP (form): {job_id} — {source_url}")
            continue

        # Skip if already fetched (idempotency)
        if jd_file_path.exists():
            summary["skipped_cached"] += 1
            print(f"  SKIP (cached): {job_id}")
            continue

        if dry_run:
            print(f"  DRY-RUN: would fetch {job_id} — {source_url}")
            continue

        # Fetch and process
        platform = detect_platform(source_url)
        print(f"  FETCH [{platform}]: {job_id} — {source_url}")

        html, final_url, error = fetch_url(source_url)

        if error:
            summary["failed_dead"] += 1
            summary["errors"].append({"job_id": job_id, "url": source_url, "error": error})
            print(f"    FAIL: {error}")

            # Update job record with dead link status
            _update_job_record(job, jd_status="dead_link")
            continue

        # Extract content
        content = extract_jd_content(html, platform, job.get("title"))
        if not content or len(content.strip()) < 50:
            summary["failed_dead"] += 1
            summary["errors"].append({
                "job_id": job_id, "url": source_url,
                "error": "Extracted content too short or empty"
            })
            print(f"    FAIL: Content too short/empty")
            _update_job_record(job, jd_status="extraction_failed")
            continue

        # Build full markdown with frontmatter
        frontmatter = build_frontmatter(job_id, source_url, platform)
        full_md = frontmatter + content

        # Save JD file
        jd_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(jd_file_path, "w") as f:
            f.write(full_md)

        # Update job record
        _update_job_record(job, jd_file=f"data/jds/{job_id}.md")

        summary["fetched"] += 1
        processed += 1
        print(f"    OK: saved {jd_file_path.name}")

    return summary


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


def write_summary_report(summary):
    """Write a summary report to exports/."""
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

    print(f"\nSummary report written to: {report_path}")
    return report_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    """Main entry point."""
    if argv is None:
        argv = sys.argv

    dry_run = "--dry-run" in argv
    limit = None
    if "--limit" in argv:
        idx = argv.index("--limit")
        if idx + 1 < len(argv):
            limit = int(argv[idx + 1])

    print("EA Jobs Database — JD Fetcher")
    print("=" * 40)

    # Load job records
    jobs = load_job_records()
    print(f"Found {len(jobs)} job records")

    if not jobs:
        print("No job records found in data/jobs/. Run the parser first.")
        write_summary_report({
            "total_urls": 0, "fetched": 0, "skipped_forms": 0,
            "skipped_no_url": 0, "skipped_cached": 0, "failed_dead": 0,
            "errors": [],
        })
        return 0

    # Process
    summary = process_jobs(jobs, dry_run=dry_run, limit=limit)

    # Write report
    write_summary_report(summary)

    print(f"\nDone: {summary['fetched']} fetched, "
          f"{summary['skipped_forms']} forms skipped, "
          f"{summary['failed_dead']} failed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
