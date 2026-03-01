#!/usr/bin/env python3
"""Test script for Issue #8 — Re-fetch full job descriptions from source URLs.

Phase 1: Quality scorer unit tests (must pass)
Phase 2+: Fetch-dependent tests (will fail until fetch is complete)

Exit code 0 = all Tier 1 tests pass, non-zero = failure.
Uses random.seed(42) for deterministic, reproducible test runs.
"""

import glob
import json
import os
import random
import sys

# Deterministic runs
random.seed(42)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

from jd_quality import score_jd, strip_frontmatter, JDQualityScore

passed = 0
failed = 0
warnings = 0


def test(name, condition, msg=""):
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}{' — ' + msg if msg else ''}")
        failed += 1


def warn(name, condition, msg=""):
    global passed, warnings
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  WARN: {name}{' — ' + msg if msg else ''}")
        warnings += 1


# ===================================================================
# SECTION 1: Quality Scorer — Known-Bad Content Rejection
# ===================================================================
print("\n=== Quality Scorer: Rejects Known-Bad Content ===")

# 1a. Error pages
error_page_content = """
# 404 - Page Not Found

The page you were looking for doesn't exist. You may have mistyped the address
or the page may have moved.

Go back to our homepage.
"""
score = score_jd(error_page_content, "generic")
test("Error page scores fatal", score.is_fatal, f"got score={score.total}, fatal={score.fatal_signal}")
test("Error page signal is error_page", score.fatal_signal == "error_page",
     f"got signal={score.fatal_signal}")

# 1b. Login/auth walls
login_wall_content = """
Please sign in to continue.

Email: ___________
Password: ___________

Forgot password? | Create an account
"""
score = score_jd(login_wall_content, "generic")
test("Login wall scores fatal", score.is_fatal, f"got score={score.total}, fatal={score.fatal_signal}")

# 1c. Cookie banner only
cookie_content = """
We use cookies to improve your experience.

Accept all cookies | Cookie preferences | Cookie policy

Data protection notice: We collect data in accordance with GDPR regulations.
"""
score = score_jd(cookie_content, "generic")
test("Cookie banner scores < 40", score.total < 40, f"got score={score.total}")

# 1d. Empty SPA shell (Ashby failure mode)
spa_shell = """<div id="root"></div>"""
score = score_jd(spa_shell, "ashby")
test("SPA shell scores < 40", score.total < 40, f"got score={score.total}")

# 1e. Expired posting
expired_content = """
This position is no longer available.

Check out our other open positions.
"""
score = score_jd(expired_content, "greenhouse")
test("Expired posting scores fatal", score.is_fatal,
     f"got score={score.total}, fatal={score.fatal_signal}")
test("Expired posting signal is expired_posting",
     score.fatal_signal == "expired_posting",
     f"got signal={score.fatal_signal}")

# 1f. Nav-only page
nav_content = """
Skip to content

Home | About | Products | Pricing | Blog | Contact

© 2024 Company Inc. All rights reserved. Privacy Policy | Terms of Service
"""
score = score_jd(nav_content, "generic")
test("Nav-only page scores < 40", score.total < 40, f"got score={score.total}")

# ===================================================================
# SECTION 2: Quality Scorer — Accepts Well-Formed JDs
# ===================================================================
print("\n=== Quality Scorer: Accepts Well-Formed JDs ===")

well_formed_jd = """---
job_id: test-org--senior-engineer--2026-01
source_url: https://example.com/jobs/123
fetched_date: 2026-01-15
platform: greenhouse
---

# Senior Software Engineer

## About the Role

We are looking for a Senior Software Engineer to join our growing team. In this role,
you will design, build, and maintain scalable systems that support our mission to
improve the world through effective giving.

## Responsibilities

- Design and implement new features for our donation platform
- Collaborate with product managers and designers to define technical solutions
- Mentor junior engineers and contribute to team development
- Write clean, well-tested code and participate in code reviews
- Help shape engineering best practices and architecture decisions

## Qualifications

### Required
- 5+ years of experience in software engineering
- Bachelor's degree in Computer Science or equivalent practical experience
- Strong proficiency in Python, TypeScript, or similar languages
- Experience with cloud platforms (AWS, GCP, or Azure)
- Track record of delivering high-quality software in a team environment

### Preferred
- Experience with data pipelines and analytics systems
- Familiarity with machine learning workflows
- Previous work in the nonprofit or social impact sector
- Contributions to open source projects

## Compensation and Benefits

- Salary: $150,000 - $200,000 annually, depending on experience
- Health insurance, dental, and vision coverage
- 401(k) with employer matching
- Flexible remote/hybrid work arrangement
- 25 days paid time off plus company holidays
- Professional development budget
- Visa sponsorship available

## How to Apply

Submit your application through our careers page. Include your resume and a brief
cover letter explaining why you're interested in this role and our mission.

Application deadline: March 15, 2026

We are an equal opportunity employer and value diversity. We do not discriminate on
the basis of race, religion, color, national origin, gender, sexual orientation,
age, marital status, veteran status, or disability status.
"""

score = score_jd(well_formed_jd, "greenhouse")
test("Well-formed JD scores >= 60", score.total >= 60, f"got score={score.total}")
test("Well-formed JD not fatal", not score.is_fatal, f"fatal={score.fatal_signal}")
test("Well-formed JD tier is promote", score.tier == "promote", f"got tier={score.tier}")
test("Well-formed JD length score > 0", score.length_score > 0,
     f"got length={score.length_score}")
test("Well-formed JD structure score > 0", score.structure_score > 0,
     f"got structure={score.structure_score}")
test("Well-formed JD vocabulary score > 0", score.vocabulary_score > 0,
     f"got vocabulary={score.vocabulary_score}")

# ===================================================================
# SECTION 3: Quality Scorer — Old 80K Summaries Score Low
# ===================================================================
print("\n=== Quality Scorer: Old 80K Summaries Score Low ===")

summary_1 = """---
job_id: 80000-hours--expression-of-interest-contract-video-editor-podcast-team--2026-02
source_url: https://80000hours.org/2026/02/expression-of-interest-contract-video-editor-for-the-podcast-team/
fetched_date: 2026-02-28
platform: 80k-hours
---

* In this role, you'll edit long-form podcast episodes to a high standard using DaVinci Resolve.
* Clean and balance audio to ensure consistent quality across episodes.
* Implement editorial and technical cuts to improve pacing while maintaining content depth.
* Deliver polished edited files to deadline and flag issues early."""

summary_2 = """---
job_id: 80000-hours--get-career-advising--2020-01
source_url: https://80000hours.org/speak-with-us/?int_campaign=job-board
fetched_date: 2026-02-28
platform: 80k-hours
---

* In this program, you will have a call with a member of the 80,000 hours advising team who will give you personalised advice. They'll help you:
* Review your options: Advisors help you evaluate causes and high-impact career options.
* Make introductions: Advisors can introduce you to experts and hiring managers in relevant fields.
* Suggest next career steps: Advisors can provide guidance on practical next steps, such as suggesting promising job opportunities."""

summary_3 = """---
job_id: 80000-hours--technical-ai-safety-upskilling-resources--2026-02
source_url: https://80000hours.org/2025/06/technical-ai-safety-upskilling-resources/
fetched_date: 2026-02-28
platform: 80k-hours
---

* Sometimes, our advising team speaks to people who have enthusiasm for technical AI safety and a related skill set but need concrete ideas for how to enter the field. This list was developed in consultation with our advisors to find the resources they commonly share.
* List includes articles, newsletters, podcasts, courses, idea lists, advice, fellowships, and organisations."""

for i, summary in enumerate([summary_1, summary_2, summary_3], 1):
    score = score_jd(summary, "80k-hours")
    test(f"80K summary #{i} scores < 50", score.total < 50,
         f"got score={score.total}")
    test(f"80K summary #{i} not promoted", score.tier != "promote",
         f"got tier={score.tier}")

# ===================================================================
# SECTION 4: Quality Scorer — Dimension Isolation
# ===================================================================
print("\n=== Quality Scorer: Dimension Isolation ===")

# Very short content should get low length score
short_content = "This is a job."
score = score_jd(short_content, "generic")
test("Very short content: length_score == 0", score.length_score == 0,
     f"got {score.length_score}")

# Content with many headings should get high structure score
structured_content = """
## About the Role
Some content here about the role and responsibilities.

## Responsibilities
- Do this important thing
- Handle that important task
- Manage the other critical workflow

## Qualifications
- 5+ years of experience
- Bachelor's degree required

## Benefits
- Health insurance
- Remote work
- Professional development

## How to Apply
Submit your application online.
"""
score = score_jd(structured_content, "generic")
test("Structured content: structure_score >= 15", score.structure_score >= 15,
     f"got {score.structure_score}")

# Content with JD vocabulary should get vocabulary score
vocab_content = "a " * 500  # Pad to avoid length penalty
vocab_content += """
The candidate should have experience in a senior role reporting to the manager.
This is a full-time remote position with salary, benefits, and health insurance.
The team is looking for someone with a bachelor's degree and 5+ years of experience.
Visa sponsorship is available. Application deadline is next month.
"""
score = score_jd(vocab_content, "generic")
test("Vocabulary-rich content: vocabulary_score >= 10", score.vocabulary_score >= 10,
     f"got {score.vocabulary_score}")

# ===================================================================
# SECTION 5: Quality Scorer — Fatal Signal Exception for Long Content
# ===================================================================
print("\n=== Quality Scorer: Fatal Signal Exception ===")

# A real JD (>2000 chars) that mentions "page not found" shouldn't be fatal
long_jd_with_fatal_phrase = "x" * 2100 + "\n\nNote: if page not found, contact HR.\n"
score = score_jd(long_jd_with_fatal_phrase, "generic")
test("Long content with fatal phrase: NOT fatal", not score.is_fatal,
     f"fatal={score.fatal_signal}")
test("Long content with fatal phrase: gets penalty", score.total < 100,
     f"got score={score.total}")

# Short content with same phrase SHOULD be fatal
short_with_fatal = "Page not found. The job listing has been removed."
score = score_jd(short_with_fatal, "generic")
test("Short content with fatal phrase: IS fatal", score.is_fatal,
     f"fatal={score.fatal_signal}")

# ===================================================================
# SECTION 6: Quality Scorer — Frontmatter Stripping
# ===================================================================
print("\n=== Quality Scorer: Frontmatter Handling ===")

content_with_fm = """---
job_id: test
source_url: https://example.com
fetched_date: 2026-01-01
platform: generic
---

Page not found. This URL doesn't exist."""

score = score_jd(content_with_fm, "generic")
test("Frontmatter stripped before scoring", score.is_fatal,
     f"Should detect fatal in body, got fatal={score.fatal_signal}")

# Frontmatter length shouldn't count toward content length
fm_body = strip_frontmatter(content_with_fm)
test("strip_frontmatter removes YAML block", "job_id" not in fm_body,
     f"body still contains frontmatter: {fm_body[:50]}")

# ===================================================================
# SECTION 7: Quality Scorer — Platform-Specific Validation
# ===================================================================
print("\n=== Quality Scorer: Platform-Specific Validation ===")

# Ashby SPA shell
ashby_shell = '<div id="root"></div><script src="/app.js"></script>'
score = score_jd(ashby_shell, "ashby")
test("Ashby SPA shell: platform_score <= 5", score.platform_score <= 5,
     f"got {score.platform_score}")

# Workable SPA shell
workable_shell = '<div id="root"></div><div class="wkb-loading"></div>'
score = score_jd(workable_shell, "workable")
test("Workable SPA shell: platform_score <= 5", score.platform_score <= 5,
     f"got {score.platform_score}")

# Google Docs with access restriction
gdocs_restricted = "You need access. Ask for access or sign in to another account."
score = score_jd(gdocs_restricted, "google-docs")
test("Google Docs restricted: platform_score == 0", score.platform_score == 0,
     f"got {score.platform_score}")

# ===================================================================
# SECTION 8: Quality Scorer — Tier Classification
# ===================================================================
print("\n=== Quality Scorer: Tier Classification ===")

# Fatal → quarantine
score = score_jd("This position is no longer available.", "greenhouse")
test("Fatal → quarantine tier", score.tier == "quarantine", f"got {score.tier}")

# Low score → quarantine
score = score_jd("Hello.", "generic")
test("Low score → quarantine tier", score.tier == "quarantine",
     f"got tier={score.tier}, score={score.total}")

# Ensure well-formed JD → promote
score = score_jd(well_formed_jd, "greenhouse")
test("Good JD → promote tier", score.tier == "promote",
     f"got tier={score.tier}, score={score.total}")

# ===================================================================
# SECTION 9: Fetch-Dependent Tests (Phase 2+)
# ===================================================================
print("\n=== Fetch-Dependent Tests (Phase 2+) ===")

# These tests verify the fetch/promote pipeline. They will fail until Phase 2 is complete.

# 9a. No file count regression
jd_files = glob.glob(os.path.join(PROJECT_ROOT, "data", "jds", "*.md"))
test("JD file count >= 834", len(jd_files) >= 834,
     f"got {len(jd_files)} files (need >= 834)")

# 9b. Staging directory exists (Phase 2)
staging_dir = os.path.join(PROJECT_ROOT, "data", "jds-staging")
warn("Staging directory exists", os.path.isdir(staging_dir),
     "data/jds-staging/ not yet created (Phase 2)")

# 9c. Backup directory exists (Phase 2)
backup_dir = os.path.join(PROJECT_ROOT, "data", "jds-backup")
warn("Backup directory exists", os.path.isdir(backup_dir),
     "data/jds-backup/ not yet created (Phase 2)")

# 9d. Fetch report exists (Phase 2)
report_path = os.path.join(PROJECT_ROOT, "exports", "jd_refetch_report.json")
if os.path.exists(report_path):
    with open(report_path) as f:
        report = json.load(f)
    required_keys = ["total", "fetched", "failed", "skipped", "promoted",
                     "quarantined", "review_queue", "by_platform"]
    missing = [k for k in required_keys if k not in report]
    test("Fetch report has required keys", not missing,
         f"missing keys: {missing}")
else:
    warn("Fetch report exists", False, "exports/jd_refetch_report.json not yet created (Phase 2)")

# 9e. Quarantine file exists (Phase 2)
quarantine_path = os.path.join(PROJECT_ROOT, "exports", "jd_quarantine.json")
warn("Quarantine manifest exists", os.path.exists(quarantine_path),
     "exports/jd_quarantine.json not yet created (Phase 2)")

# 9f. Review queue exists (Phase 2)
review_md_path = os.path.join(PROJECT_ROOT, "exports", "jd_review_queue.md")
review_json_path = os.path.join(PROJECT_ROOT, "exports", "jd_review_queue.json")
warn("Review queue (md) exists", os.path.exists(review_md_path),
     "exports/jd_review_queue.md not yet created (Phase 2)")
warn("Review queue (json) exists", os.path.exists(review_json_path),
     "exports/jd_review_queue.json not yet created (Phase 2)")

# 9g. Frontmatter integrity on all JD files
print("\n=== Frontmatter Integrity ===")
frontmatter_ok = 0
frontmatter_bad = 0
required_fm_fields = ["job_id", "source_url", "fetched_date", "platform"]
for jd_path in jd_files[:50]:  # Sample 50 for speed
    with open(jd_path) as f:
        content = f.read()
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            fm_text = content[3:end]
            has_all = all(field + ":" in fm_text for field in required_fm_fields)
            if has_all:
                frontmatter_ok += 1
            else:
                frontmatter_bad += 1
        else:
            frontmatter_bad += 1
    else:
        frontmatter_bad += 1

total_checked = frontmatter_ok + frontmatter_bad
test(f"Frontmatter integrity ({frontmatter_ok}/{total_checked} OK)",
     frontmatter_bad == 0,
     f"{frontmatter_bad} files have missing/malformed frontmatter")

# 9h. Stratified platform quality (Phase 2 — will warn until fetch is done)
print("\n=== Stratified Platform Quality (Phase 2) ===")

# Build platform → files mapping from actual JD files
platform_files = {}
for jd_path in jd_files:
    with open(jd_path) as f:
        content = f.read()
    # Extract platform from frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            fm = content[3:end]
            for line in fm.split("\n"):
                if line.startswith("platform:"):
                    platform = line.split(":", 1)[1].strip()
                    platform_files.setdefault(platform, []).append(jd_path)
                    break

for platform, files in sorted(platform_files.items()):
    if platform == "80k-hours":
        continue  # These are all summaries pre-fetch
    sample_size = min(14, len(files))
    sample = random.sample(files, sample_size)
    good = 0
    for fp in sample:
        with open(fp) as f:
            content = f.read()
        s = score_jd(content, platform)
        if s.total >= 60:
            good += 1
    pct = good / sample_size * 100 if sample_size > 0 else 0
    threshold = 70
    warn(f"Platform '{platform}' quality: {good}/{sample_size} ({pct:.0f}%) >= 60",
         pct >= threshold,
         f"Only {pct:.0f}% pass (need {threshold}%) — expected until Phase 2 fetch")


# ===================================================================
# Summary
# ===================================================================
print("\n" + "=" * 50)
print(f"Results: {passed} passed, {failed} failed, {warnings} warnings")
print("=" * 50)

if failed > 0:
    print(f"\nFAILED — {failed} test(s) did not pass")
    sys.exit(1)
else:
    print(f"\nPASSED — all tests green")
    sys.exit(0)
