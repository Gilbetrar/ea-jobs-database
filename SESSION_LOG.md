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
