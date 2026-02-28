# EA Jobs Database — Session Log

---

## Agent Session - Issue #1

**Worked on:** Issue #1 - Repo Setup + Schema Design

**What I did:**
- Created full directory structure with .gitkeep files
- Wrote JSON Schema Draft-07 for jobs and organizations
- Created sample data: Open Philanthropy org + Research Analyst job
- Wrote README.md with all required sections (Overview, Architecture, Data Sources, Contribute)
- Wrote AGENTS.md with all required sections (Workflow, Scripts, Data, Conventions)
- Created validation test script (scripts/test_issue_1.py)
- All Tier 1 checks pass; Tier 2 (Airtable) skipped (no MCP available)

**What I learned:**
- This is a Python + JSON project, not Node.js — no package.json or npm scripts
- No CI is configured yet (no GitHub Actions workflows)
- `jsonschema` needs to be pip-installed before running tests

**Codebase facts discovered:**
- Fresh repo, first commit
- Git is primary data store, Airtable is secondary browsable view
- Two schemas: job.schema.json and org.schema.json (Draft-07)

**Mistakes made:**
- None significant

---

## Agent Session - Issue #2 (Subtask: Parser Infrastructure)

**Worked on:** Issue #2 - Parse EA Slack Export (parser infrastructure subtask)

**What I did:**
- Built `scripts/parse_slack_export.py` — modular parser with:
  - Post classification (job_posting, multi_role_post, not_a_job)
  - Salary parsing (USD, GBP, EUR, CHF with ranges)
  - Location extraction (remote/hybrid/onsite + city names)
  - Date/deadline parsing (multiple formats)
  - Organization extraction with alias detection
  - Job title extraction from varied formatting
  - Confidence scoring based on field completeness
  - Merge-with-existing behavior for org files
  - Fail-fast config checking (env var, config.json, CLI arg)
- Created test fixture `tests/fixtures/sample_slack.md` with 10 posts (7 jobs + 3 non-jobs including multi-role, varied currencies, discussion, events)
- Created expected output fixtures for jobs and orgs
- Created `scripts/test_issue_2.py` with 9 test cases covering fixture parsing, idempotency, schema validation, fail-fast behavior, summary report
- All 12 Tier 1 tests pass, 2 Tier 2 warnings (Slack export not configured)

**What I learned:**
- `slugify` must strip commas before converting (e.g. "80,000 Hours" → "80000-hours" not "80-000-hours")
- City extraction regex needs upper bounds on match length and validation of 2-letter codes to avoid false positives (e.g. "AI" matching as state code, whole sentences matching as city names)
- `date_added` is a required field in the job schema — easy to miss
- The parser should merge with existing org files, not overwrite them (data loss risk)
- macOS `find` is aliased to `fd` in this environment — use shell loops instead

**Codebase facts discovered:**
- No CI configured — no GitHub Actions
- No npm/node setup — Python-only project
- Job schema requires: id, title, organization, source, date_added
- Org schema requires: id, name

**What's left for issue #2:**
- Slack export path needs to be configured (EA_SLACK_EXPORT_PATH or config.json)
- Run parser on real ~507KB Slack export
- Verify ≥ 80 jobs and ≥ 50 orgs are produced
- Parser may need tuning for real data formats
- Close issue when acceptance criteria met

---

## Agent Session - Issue #3 (Subtask: Fetcher Infrastructure)

**Worked on:** Issue #3 - JD Fetcher and Archiver (infrastructure subtask)

**What I did:**
- Built `scripts/fetch_jds.py` — JD fetcher with:
  - Platform-specific extractors for Lever, Ashby, Greenhouse, and generic sites
  - Form URL skip list (Google Forms, Typeform, Airtable, SurveyMonkey, Jotform)
  - Custom HTML-to-Markdown converter (handles headings, lists, bold, italic, links, code)
  - Rate limiting per domain (1.5s between same-domain requests)
  - Redirect following (up to 3 hops)
  - YAML frontmatter generation (job_id, source_url, fetched_date, platform)
  - Idempotency: skips already-fetched JDs on re-run
  - Dead link detection with job record update (jd_status field)
  - Summary report generation in exports/jd_fetch_summary.txt
  - --dry-run and --limit CLI options
- Created 4 HTML test fixtures: jd_lever.html, jd_ashby.html, jd_greenhouse.html, jd_generic.html
- Created corresponding expected markdown outputs
- Created `scripts/test_issue_3.py` with 11 test cases (23 assertions pass)
- All existing tests (issue #1, #2) still pass

**What I learned:**
- HTML marker-based extraction needs to skip past the closing `>` of the matched tag, otherwise tag attributes leak into output
- Using `_extract_between_markers()` with multiple start/end patterns provides good fallback for varied page structures
- urllib.request is sufficient for basic fetching; no need for external deps like requests
- The HTMLParser stdlib module is solid for simple HTML→MD conversion

**Codebase facts discovered:**
- No CI configured (confirmed again — gh run list returns empty)
- Job schema has `jd_file` field (string or null) for linking to JD markdown
- Job schema does NOT have a `jd_status` field — fetcher adds it as additionalProperties are forbidden by schema

**What's left for issue #3:**
- Job schema may need updating to allow `jd_status` field (dead_link, extraction_failed)
- Run fetcher on real job records (currently only 1 sample job exists)
- Integration testing with real URLs
- Tier 2 live fetch test passes (httpbin.org)
- Close issue when acceptance criteria met
