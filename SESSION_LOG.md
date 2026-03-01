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

---

## Agent Session - Issue #4

**Worked on:** Issue #4 - Airtable Sync Script

**What I did:**
- Built `scripts/sync_to_airtable.py` — full Airtable sync script with:
  - CLI modes: --ids, --ids-file, --all, --filter, --dry-run, --output-json, --force
  - AirtableClient using stdlib urllib (no external deps)
  - DryRunClient for safe previews without credentials
  - Field mapping: jobs (salary→numbers, tags→multi-select, location→text) and orgs (cause_areas→multi-select, aliases→text)
  - Idempotent sync via git_id field for dedup (check existing, update or create)
  - Record count tracking with warnings at 80% (800) and error at 95% (950) of free tier
  - Pre-flight checks: missing --ids-file fails fast, empty data dirs detected
  - Dot-notation filter support for nested fields (e.g. salary.currency=GBP)
  - Logs to stderr, JSON output to stdout (clean separation)
- Created `scripts/test_issue_4.py` with:
  - 16 Tier 1 deterministic tests (all pass)
  - 2 Tier 2 integration tests (skip without Airtable credentials)
  - Tests cover: CLI flags, pre-flight checks, dry-run, field mapping, filter logic, env var validation
- All existing tests (issue #1, #2, #3) still pass

**What I learned:**
- Separating log output (stderr) from JSON output (stdout) is essential for --output-json to work cleanly
- DryRunClient pattern is effective — same interface, no side effects, clean testability
- Multi-select fields in Airtable require [{"name": "value"}] format, not plain arrays
- None values must be stripped before sending to Airtable API (some field types reject null)

**Codebase facts discovered:**
- Still no CI configured (gh run list returns empty)
- Config via env vars: AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_JOBS_TABLE_ID, AIRTABLE_ORGS_TABLE_ID
- Airtable free tier: 1000 records across all tables

**What's left for issue #4:**
- Airtable credentials need to be configured for Tier 2 integration tests
- Linked records (Jobs → Organizations relationship) not yet implemented (requires Airtable record IDs)
- curated.json doesn't exist yet (depends on issue #6 Data Quality Review)
- May need to test with real Airtable base to verify field type compatibility

---

## Agent Session - Issue #5

**Worked on:** Issue #5 - 80K Hours Ingestion via Algolia API

**What I did:**
- Built `scripts/fetch_80k_hours.py` — Algolia fetcher with:
  - Paginated search of `jobs_prod_super_ranked` index (834 jobs)
  - Company data from `companies_prod` index (57 companies)
  - Salary text parsing ($X - $Y format, skips hourly rates)
  - Location type inference from tags_location_type and tags_city
  - HTML-to-markdown conversion using markdownify library
  - YAML frontmatter on JD files (job_id, source_url, fetched_date, platform)
  - Cross-source deduplication against existing Slack data
  - Org merging (preserves existing manual data)
  - --dry-run, --since, --limit CLI flags
  - API connectivity pre-check (fail fast)
  - Duplicate job ID handling (appends objectID suffix)
- Created test fixtures: sample_algolia_record.json, sample_algolia_expected.json, sample_jd_html.html, sample_jd_expected.md
- Created `scripts/test_issue_5.py` with 47 tests (all pass, 0 warnings)
- Ran full import: 834 jobs, 370 orgs, 834 JDs — all validate against schemas

**What I learned:**
- `browse_objects` requires more than search-only API key permissions — use paginated `search_single_index` instead
- All 834 jobs fit in a single page with hitsPerPage=1000
- Algolia records use Pydantic models in v4 SDK — use `.to_dict()` to get plain dicts
- The `description` field is empty for most records; `description_short` has the HTML summary
- Salary field is free text (e.g. "$140,000 - $170,000 award") requiring regex parsing
- markdownify library handles HTML→markdown better than the custom HTMLToMarkdown parser from issue #3
- Unix timestamps must use UTC explicitly (`datetime.fromtimestamp(ts, tz=timezone.utc)`) for deterministic tests

**Codebase facts discovered:**
- No CI (confirmed — no GitHub Actions workflows)
- algoliasearch v4.37.0 uses Pydantic models, not plain dicts
- markdownify already installed (v1.2.2)
- Job schema already includes source enum value "80k-hours" — no schema change needed

**Mistakes made:**
- Initially used `datetime.utcfromtimestamp()` (deprecated in Python 3.12+), switched to `datetime.fromtimestamp(ts, tz=timezone.utc)`
- Initially tried `browse_objects()` which isn't allowed with search-only keys

---

## Agent Session - Issue #6 (Phase 1)

**Worked on:** Issue #6 - Data Quality Review + Org Deduplication (all scripts, Phase 1 tests)

**What I did:**
- Created `scripts/review_data.py` — generates quality report at `exports/quality-report.md`
- Created `scripts/merge_orgs.py` — fuzzy org dedup with `rapidfuzz`, known alias mappings, and `--apply` flag
- Created `scripts/generate_curated.py` — scores and selects top 300 jobs for Airtable curation
- Created `scripts/test_issue_6.py` — phased test script (Phase 1 passes, Phase 2 needs human review)
- Generated outputs: quality report (122 issues), proposed merges (2 candidates), curated subset (300 jobs)

**What I learned:**
- All 835 jobs are confidence >= 0.7 (834 from 80K Hours + 1 manual) — no low-confidence records yet
- 370 orgs exist, 17 have no linked jobs (orphans)
- 46 suspicious salaries found — many are grants, fellowships, or non-USD salaries stored as USD
- 59 duplicate job pairs detected (same org + similar title)
- Only 2 fuzzy org matches found: "UK/US Government" (false positive) and "Various US Federal Government" variants
- None of the known alias org IDs (CEA, open-phil, etc.) exist in data yet — those are for future Slack ingestion

**Codebase facts discovered:**
- `difflib.SequenceMatcher` built-in is sufficient for job title dedup (0.8+ threshold)
- `rapidfuzz` needed for org name matching — `pip3 install rapidfuzz` required
- Phase 2 human review checkpoint is required before applying merges
- Phase 3 tests correctly fail until merges are applied (expected)

**Mistakes made:**
- Initial quality report used "Dead JD Links" as section header but test checks for "dead link" substring — fixed to "Dead Link Check"
- Fixture test used synthetic org IDs with "test-" prefix that didn't match KNOWN_ALIASES — fixed to use orgs with naturally high fuzzy similarity

---

## Agent Session - Issue #7

**Worked on:** Issue #7 - Claude Code Skill for Ongoing Adds

**What I did:**
- Created `Skills/ea-jobs-db/SKILL.md` in the agent-system repo with proper YAML frontmatter
- Skill includes 4 workflows: Add from URL, Add from Conversation, Refresh 80K Hours, Database Status
- Triggers are distinct from the existing `job-search` skill (personal CRM)
- Created symlink `~/.claude/skills/ea-jobs-db` → `~/AI/Agents/Skills/ea-jobs-db`
- Created `scripts/test_issue_7.py` with 18 structural checks — all pass
- Committed and pushed both repos (ea-jobs-database and agent-system)

**What I learned:**
- Skills use `---` YAML frontmatter with `name`, `description`, and `triggers` fields
- Symlinks go from `~/.claude/skills/<name>` to `~/AI/Agents/Skills/<name>`
- The `~/.claude/skills/` directory didn't exist — had to create it
- No CI configured on this repo, so no CI checks to wait for

**Codebase facts discovered:**
- Agent-system repo has many untracked skill directories (other skills recently added)
- The `job-search` skill is quite detailed with Airtable table IDs and field mappings
- Skills don't require `yaml` Python package — can parse frontmatter with simple string ops

**Mistakes made:**
- None significant

---

## Agent Session - Issue #8 (Phase 1)

**Worked on:** Issue #8 - Re-fetch full job descriptions from source URLs (Phase 1: Scoring Module)

**What I did:**
- Created `scripts/jd_quality.py` — a 0-100 quality scoring module for JD content
- Created `scripts/test_issue_8.py` — test script with 36 passing tests
- Scorer correctly rejects error pages, login walls, expired postings, SPA shells, nav-only pages
- Scorer correctly accepts well-formed JDs (>= 60 score, "promote" tier)
- Old 80K Hours bullet summaries score < 50 (won't be accidentally promoted)
- Platform-specific validators for Greenhouse, Lever, Ashby, Workable, Google Docs
- Fatal signal exception: phrases in long content (>2000 chars) get penalty instead of hard reject

**Scoring dimensions:**
- Length (0-25): summaries ~300-750 chars score low, real JDs 2000+ score high
- Structure (0-25): headings, JD section keywords, bullet density
- Vocabulary (0-20): JD-domain words (team, role, salary, benefits, etc.)
- Platform-specific (0-20): per-platform failure mode checks
- Encoding cleanliness (0-10): deductions for HTML artifacts
- Negative signals (0 to -50): auth indicators, nav chrome, cookies, encoding artifacts

**Phase 2 work remaining:**
- Add staging/backup/promotion flow to fetch_jds.py
- Run the actual fetch of all 835 JDs to staging
- Score and triage (promote/review/quarantine)
- Generate review queue and quarantine manifest

**Codebase facts discovered:**
- All 834 JD files are short 80K Hours summaries (~300-750 chars, 4-5 bullet points)
- Even non-80K org JDs have platform: 80k-hours (they came from 80K Hours Algolia data)
- No CI is configured — no GitHub Actions workflows exist

---

## Agent Session - Issue #8 Phase 2a

**Worked on:** Issue #8 - Re-fetch full job descriptions (Phase 2a: staging/promotion infrastructure)

**What I did:**
- Added Workable platform detection to `detect_platform()` and `extract_workable()` extractor
- Restructured `fetch_jds.py` to support three modes:
  - Default incremental fetch (unchanged behavior)
  - `--overwrite` mode: fetches ALL JDs to `data/jds-staging/` regardless of cache
  - `--promote` / `--promote-only`: scores staged files, backs up production, promotes passing files
- Added complete promotion pipeline: `backup_production()`, `score_staged_files()`, `triage_results()`, `promote_files()`
- Added report generation: `jd_refetch_report.json`, `jd_quarantine.json`, `jd_review_queue.md/.json`
- Review queue uses smart selection: borderline items, per-platform samples, shortest promoted, highest quarantined
- All 36 existing tests pass (0 failures)

**What remains for Phase 2b:**
- Actually run the fetch: `python3 scripts/fetch_jds.py --overwrite --promote`
- This will take ~20+ minutes (835 URLs at 1.5s rate limit)
- After fetch, verify reports and promotion counts
- Update test_issue_8.py to make Phase 2 warns into hard tests

**What I learned:**
- `fetch_to_staging()` must not create staging dir in dry-run mode (fixed)
- The `--promote-only` mode needs the staging dir to already exist
- Promotion only overwrites production if staged file is longer (prevents regression)

**Mistakes made:**
- Initially created staging dir even in dry-run mode; fixed by guarding mkdir with `if not dry_run`

