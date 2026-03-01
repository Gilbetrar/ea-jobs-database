#!/usr/bin/env python3
"""JD quality scoring module for the EA Jobs Database.

Scores markdown JD content on a 0-100 scale using pattern matching and heuristics.
No ML, no external dependencies — just stdlib.

Scoring dimensions:
- Length (0-25): Exploits the size gap between summaries and real JDs
- Structure (0-25): Headings, JD section keywords, bullet density
- Vocabulary (0-20): JD-domain words vs generic web text
- Platform-specific (0-20): Per-platform failure mode checks
- Encoding cleanliness (0-10): Deductions for artifacts
- Negative signals (0 to -50): Penalty for error pages, nav chrome, etc.

Fatal signals cause immediate quarantine regardless of score.
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Scoring result
# ---------------------------------------------------------------------------

@dataclass
class JDQualityScore:
    """Quality score for a JD file."""
    total: int = 0
    length_score: int = 0
    structure_score: int = 0
    vocabulary_score: int = 0
    platform_score: int = 0
    encoding_score: int = 0
    negative_penalty: int = 0
    fatal_signal: Optional[str] = None
    breakdown: dict = field(default_factory=dict)

    @property
    def is_fatal(self):
        return self.fatal_signal is not None

    @property
    def tier(self):
        """Return promotion tier: 'promote', 'review', or 'quarantine'."""
        if self.is_fatal:
            return "quarantine"
        if self.total >= 60:
            return "promote"
        if self.total >= 40:
            return "review"
        return "quarantine"


# ---------------------------------------------------------------------------
# Fatal signals — hard reject regardless of score
# ---------------------------------------------------------------------------

FATAL_PATTERNS = [
    (r"this\s+position\s+is\s+no\s+longer\s+available", "expired_posting"),
    (r"this\s+job\s+is\s+no\s+longer\s+available", "expired_posting"),
    (r"job\s+has\s+been\s+(filled|closed|removed)", "expired_posting"),
    (r"this\s+posting\s+has\s+(expired|closed|been\s+removed)", "expired_posting"),
    (r"no\s+longer\s+accepting\s+applications", "expired_posting"),
    (r"this\s+role\s+has\s+been\s+filled", "expired_posting"),
    (r"\b404\b.*page\s+not\s+found", "error_page"),
    (r"page\s+not\s+found", "error_page"),
    (r"could\s+not\s+be\s+found", "error_page"),
    (r"the\s+page\s+you.+looking\s+for.+doesn.t\s+exist", "error_page"),
    (r"please\s+sign\s+in", "auth_wall"),
    (r"log\s+in\s+to\s+view", "auth_wall"),
    (r"create\s+an\s+account\s+to", "auth_wall"),
    (r"you\s+need\s+access", "auth_wall"),
    (r"request\s+access", "auth_wall"),
]


def check_fatal_signals(content, content_length):
    """Check for fatal signals. Returns signal name or None.

    Exception: Fatal phrases in content >2000 chars get a penalty instead
    of hard rejection (a real JD might mention boilerplate).
    """
    content_lower = content.lower()
    for pattern, signal in FATAL_PATTERNS:
        if re.search(pattern, content_lower):
            # Exception: long content gets penalty instead of fatal
            if content_length > 2000:
                return None
            return signal
    return None


# ---------------------------------------------------------------------------
# Negative pattern categories (penalty, not fatal)
# ---------------------------------------------------------------------------

AUTH_PATTERNS = [
    r"\bsso\b",
    r"forgot\s+password",
    r"username.*password",
    r"sign\s+in\s+with",
    r"log\s+in\s+with",
]

NAV_PATTERNS = [
    r"skip\s+to\s+content",
    r"skip\s+to\s+main",
    r"©\s*\d{4}",
    r"copyright\s+\d{4}",
    r"all\s+rights\s+reserved",
    r"privacy\s+policy",
    r"terms\s+of\s+(service|use)",
]

COOKIE_PATTERNS = [
    r"we\s+use\s+cookies",
    r"accept\s+all\s+cookies",
    r"cookie\s+(policy|preferences|settings|consent)",
    r"data\s+protection",
    r"gdpr",
]

ENCODING_ARTIFACT_PATTERNS = [
    r"\\u[0-9a-fA-F]{4}",
    r"CDATA",
    r"\{[^}]*font-family[^}]*\}",
    r"<script",
    r"<style",
    r"\.css\b",
    r"var\s+\w+\s*=",
]

REPETITION_THRESHOLD = 3  # Same line appearing this many times = penalty


def score_negative_patterns(content):
    """Score negative patterns. Returns (penalty, details)."""
    content_lower = content.lower()
    total_penalty = 0
    details = {}

    # Auth indicators: -15 each, max -30
    auth_hits = sum(1 for p in AUTH_PATTERNS if re.search(p, content_lower))
    auth_penalty = min(auth_hits * 15, 30)
    if auth_penalty:
        total_penalty += auth_penalty
        details["auth"] = -auth_penalty

    # Nav chrome: -5 each, max -20
    nav_hits = sum(1 for p in NAV_PATTERNS if re.search(p, content_lower))
    nav_penalty = min(nav_hits * 5, 20)
    if nav_penalty:
        total_penalty += nav_penalty
        details["nav"] = -nav_penalty

    # Cookie/GDPR: -10 each, max -20
    cookie_hits = sum(1 for p in COOKIE_PATTERNS if re.search(p, content_lower))
    cookie_penalty = min(cookie_hits * 10, 20)
    if cookie_penalty:
        total_penalty += cookie_penalty
        details["cookie"] = -cookie_penalty

    # Encoding artifacts: -5 each, max -15
    enc_hits = sum(1 for p in ENCODING_ARTIFACT_PATTERNS if re.search(p, content_lower))
    enc_penalty = min(enc_hits * 5, 15)
    if enc_penalty:
        total_penalty += enc_penalty
        details["encoding_artifacts"] = -enc_penalty

    # Repetitive content: same line 3+ times = -10
    lines = [line.strip() for line in content.split("\n") if line.strip() and len(line.strip()) > 10]
    from collections import Counter
    line_counts = Counter(lines)
    has_repetition = any(count >= REPETITION_THRESHOLD for count in line_counts.values())
    if has_repetition:
        total_penalty += 10
        details["repetition"] = -10

    return min(total_penalty, 50), details


# ---------------------------------------------------------------------------
# Scoring dimensions
# ---------------------------------------------------------------------------

def score_length(content_length):
    """Score based on content length (0-25).

    Summaries: 300-750 chars → low score
    Real JDs: 2000+ chars → high score
    """
    if content_length < 200:
        return 0
    if content_length < 500:
        return 3
    if content_length < 1000:
        return 8
    if content_length < 1500:
        return 12
    if content_length < 2000:
        return 16
    if content_length < 3000:
        return 20
    return 25


JD_SECTION_KEYWORDS = [
    "responsibilities", "qualifications", "requirements",
    "about the role", "about the position", "about the job",
    "about us", "about the team", "about the company",
    "what you'll do", "what you will do",
    "who you are", "what we're looking for", "what we are looking for",
    "how to apply", "application process",
    "benefits", "compensation", "perks",
    "key duties", "key responsibilities",
    "experience", "skills", "education",
    "equal opportunity", "diversity",
]


def score_structure(content):
    """Score based on structure (0-25).

    Looks for markdown headings, JD section keywords, bullet density.
    """
    score = 0
    lines = content.split("\n")

    # Count markdown headings (## or ###)
    headings = [line for line in lines if re.match(r'^#{1,4}\s+\S', line)]
    heading_count = len(headings)
    if heading_count >= 4:
        score += 10
    elif heading_count >= 2:
        score += 6
    elif heading_count >= 1:
        score += 3

    # Check for JD section keywords in headings or text
    content_lower = content.lower()
    keyword_hits = sum(1 for kw in JD_SECTION_KEYWORDS if kw in content_lower)
    if keyword_hits >= 5:
        score += 10
    elif keyword_hits >= 3:
        score += 7
    elif keyword_hits >= 1:
        score += 3

    # Bullet density — real JDs have organized bullet lists
    bullet_lines = [line for line in lines if re.match(r'^\s*[-*•]\s+\S', line)]
    numbered_lines = [line for line in lines if re.match(r'^\s*\d+\.\s+\S', line)]
    list_items = len(bullet_lines) + len(numbered_lines)
    if list_items >= 8:
        score += 5
    elif list_items >= 4:
        score += 3
    elif list_items >= 2:
        score += 1

    return min(score, 25)


JD_VOCABULARY = [
    "team", "role", "candidate", "degree", "salary", "remote",
    "hybrid", "onsite", "full-time", "part-time", "contract",
    "experience", "years", "manager", "lead", "senior", "junior",
    "intern", "internship", "fellowship", "apply", "application",
    "interview", "collaborate", "stakeholder", "impact",
    "mission", "organization", "organisation",
    "reporting to", "reports to", "report to",
    "responsible for", "accountable for",
    "minimum", "preferred", "required", "desired",
    "bachelor", "master", "phd", "equivalent",
    "deadline", "start date", "compensation", "benefits",
    "health insurance", "retirement", "equity", "stock",
    "visa", "sponsorship", "relocation",
]


def score_vocabulary(content):
    """Score based on JD-domain vocabulary (0-20).

    Checks for words typical of real job descriptions.
    """
    content_lower = content.lower()
    hits = sum(1 for word in JD_VOCABULARY if word in content_lower)

    if hits >= 15:
        return 20
    if hits >= 10:
        return 15
    if hits >= 6:
        return 10
    if hits >= 3:
        return 5
    return 0


# ---------------------------------------------------------------------------
# Platform-specific validation
# ---------------------------------------------------------------------------

def validate_greenhouse(content):
    """Platform-specific checks for Greenhouse pages (0-20)."""
    content_lower = content.lower()
    score = 10  # Start at midpoint

    # Positive: has job content markers
    if any(kw in content_lower for kw in ["apply for this job", "department", "location"]):
        score += 5

    # Negative: application form leaked in
    if re.search(r"(first\s+name|last\s+name|upload\s+resume|attach\s+resume)", content_lower):
        score -= 5

    # Negative: listing page instead of single JD
    if content_lower.count("view position") > 2 or content_lower.count("apply now") > 3:
        score -= 5

    return max(0, min(score, 20))


def validate_lever(content):
    """Platform-specific checks for Lever pages (0-20)."""
    content_lower = content.lower()
    score = 10

    # Positive: has typical Lever sections
    if any(kw in content_lower for kw in ["the role", "the team", "what you'll do"]):
        score += 5

    # Negative: only got apply section
    if len(content) < 500 and "apply for this job" in content_lower:
        score -= 8

    # Negative: listing page
    if content_lower.count("view position") > 2:
        score -= 5

    return max(0, min(score, 20))


def validate_ashby(content):
    """Platform-specific checks for Ashby pages (0-20).

    CRITICAL: Ashby is heavily JS-rendered. urllib gets empty shells.
    """
    content_lower = content.lower()
    score = 10

    # SPA shell detection — the main failure mode
    if len(content) < 200:
        # Almost certainly an empty SPA shell
        if any(kw in content_lower for kw in ["root", "loading", "react", "__next"]):
            return 0
        return 2  # Very suspicious even without SPA markers

    # Positive: has actual job content
    if len(content) > 1000 and any(kw in content_lower for kw in ["about the role", "qualifications"]):
        score += 8

    return max(0, min(score, 20))


def validate_workable(content):
    """Platform-specific checks for Workable pages (0-20).

    Similar JS-rendering risk as Ashby.
    """
    content_lower = content.lower()
    score = 10

    # SPA shell detection
    if len(content) < 200:
        if any(kw in content_lower for kw in ["root", "loading", "react", "__next", "wkb-"]):
            return 0
        return 2

    if len(content) > 1000:
        score += 5

    return max(0, min(score, 20))


def validate_google_docs(content):
    """Platform-specific checks for Google Docs pages (0-20)."""
    content_lower = content.lower()
    score = 10

    # Negative: access restriction
    if "you need access" in content_lower or "request access" in content_lower:
        return 0

    # Negative: excessive inline CSS (Google Docs artifact)
    css_count = content.count("font-family:")
    if css_count >= 5:
        score -= 8

    # Positive: substantial content
    if len(content) > 1500:
        score += 5

    return max(0, min(score, 20))


def validate_generic(content):
    """Generic platform validation (0-20)."""
    content_lower = content.lower()
    score = 10

    # Negative: homepage landing page
    homepage_indicators = ["our products", "pricing", "testimonials", "sign up free", "get started"]
    homepage_hits = sum(1 for ind in homepage_indicators if ind in content_lower)
    if homepage_hits >= 2:
        score -= 8

    # Positive: substantial content with JD indicators
    if len(content) > 1500:
        score += 5
    if any(kw in content_lower for kw in ["responsibilities", "qualifications", "requirements"]):
        score += 3

    return max(0, min(score, 20))


PLATFORM_VALIDATORS = {
    "greenhouse": validate_greenhouse,
    "lever": validate_lever,
    "ashby": validate_ashby,
    "workable": validate_workable,
    "google-docs": validate_google_docs,
    "generic": validate_generic,
    "80k-hours": validate_generic,
    "unknown": validate_generic,
}


def score_platform(content, platform):
    """Run platform-specific validation (0-20)."""
    validator = PLATFORM_VALIDATORS.get(platform, validate_generic)
    return validator(content)


# ---------------------------------------------------------------------------
# Encoding cleanliness
# ---------------------------------------------------------------------------

def score_encoding(content):
    """Score encoding cleanliness (0-10). Deductions for artifacts."""
    score = 10

    # HTML entities that weren't converted
    entity_count = len(re.findall(r'&(?:amp|lt|gt|nbsp|quot|#\d+);', content))
    if entity_count > 10:
        score -= 4
    elif entity_count > 3:
        score -= 2

    # Leftover HTML tags
    tag_count = len(re.findall(r'<(?!!)/?[a-zA-Z][^>]*>', content))
    if tag_count > 5:
        score -= 4
    elif tag_count > 0:
        score -= 2

    # Mojibake / broken unicode
    if re.search(r'[\ufffd\ufffe\uffff]', content):
        score -= 2

    # CSS artifacts
    if re.search(r'\{[^}]*(?:margin|padding|display|font-size)[^}]*\}', content):
        score -= 3

    return max(0, score)


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def strip_frontmatter(content):
    """Remove YAML frontmatter from content for scoring."""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            return content[end + 3:].strip()
    return content


def score_jd(content, platform="generic"):
    """Score a JD's quality on a 0-100 scale.

    Args:
        content: The full markdown content of the JD file (may include frontmatter).
        platform: The platform the JD was fetched from.

    Returns:
        JDQualityScore with total score, dimension breakdowns, and tier.
    """
    # Strip frontmatter for scoring
    body = strip_frontmatter(content)
    body_length = len(body)

    result = JDQualityScore()

    # Check fatal signals first
    fatal = check_fatal_signals(body, body_length)
    if fatal:
        result.fatal_signal = fatal
        result.total = 0
        return result

    # Score each dimension
    result.length_score = score_length(body_length)
    result.structure_score = score_structure(body)
    result.vocabulary_score = score_vocabulary(body)
    result.platform_score = score_platform(body, platform)
    result.encoding_score = score_encoding(body)

    # Negative patterns
    neg_penalty, neg_details = score_negative_patterns(body)
    result.negative_penalty = neg_penalty
    result.breakdown = neg_details

    # Calculate total
    raw = (
        result.length_score
        + result.structure_score
        + result.vocabulary_score
        + result.platform_score
        + result.encoding_score
        - result.negative_penalty
    )
    result.total = max(0, min(100, raw))

    # Check for fatal signals in long content (they get penalty instead)
    content_lower = body.lower()
    if body_length > 2000:
        for pattern, signal in FATAL_PATTERNS:
            if re.search(pattern, content_lower):
                result.breakdown["fatal_in_long_content"] = -10
                result.total = max(0, result.total - 10)
                break

    return result
