# EA Jobs Database — Learnings

## Project Structure

```
ea-jobs-database/
├── data/jobs/       # One JSON per job: {org-id}--{role-slug}--{YYYY-MM}.json
├── data/orgs/       # One JSON per org: {org-id}.json
├── data/jds/        # Full JDs as markdown: {job-id}.md
├── scripts/         # Python scripts
├── schemas/         # JSON Schema Draft-07
├── exports/         # Generated CSVs/reports
```

## Commands That Work

```bash
python3 scripts/test_issue_1.py                          # Validate schemas, samples, docs
python3 scripts/test_issue_2.py                          # Validate Slack parser + fixtures
python3 scripts/test_issue_3.py                          # Validate JD fetcher + fixtures
python3 scripts/parse_slack_export.py path/to/export.md  # Run parser on Slack export
python3 scripts/fetch_jds.py [--dry-run] [--limit N]     # Fetch JDs from source URLs
python3 scripts/sync_to_airtable.py --dry-run --all      # Preview Airtable sync
python3 scripts/test_issue_4.py                          # Validate Airtable sync script
python3 scripts/fetch_80k_hours.py [--dry-run] [--since] # Fetch 80K Hours jobs via Algolia
python3 scripts/test_issue_5.py                          # Validate 80K Hours fetcher
pip3 install jsonschema                                  # Required dependency
pip3 install algoliasearch markdownify                   # Required for 80K Hours fetcher
pip3 install rapidfuzz                                   # Required for org dedup
python3 scripts/review_data.py                           # Generate quality report
python3 scripts/merge_orgs.py                            # Generate proposed org merges
python3 scripts/merge_orgs.py --apply                    # Apply approved merges
python3 scripts/generate_curated.py                      # Generate curated subset (300 jobs)
python3 scripts/test_issue_6.py                          # Validate issue #6 Phase 1
python3 scripts/test_issue_6.py --post-merge             # Validate Phase 3 (after merge apply)
python3 scripts/test_issue_7.py                          # Validate Claude Code skill structure
AIRTABLE_PAT=patXXX python3 scripts/bulk_upload.py                       # Bulk upload jobs to Airtable
AIRTABLE_PAT=patXXX python3 scripts/bulk_upload.py --dry-run              # Preview bulk upload
AIRTABLE_PAT=patXXX python3 scripts/bulk_upload.py --update-only          # Patch JDs on existing records
AIRTABLE_PAT=patXXX python3 scripts/bulk_upload.py --update-only --dry-run  # Preview JD patches
python3 scripts/fetch_jds.py --overwrite --promote         # Full re-fetch pipeline (fetch→score→promote)
python3 scripts/fetch_jds.py --overwrite --dry-run        # Preview what would be fetched
python3 scripts/fetch_jds.py --promote-only               # Score+promote from existing staging
python3 scripts/test_issue_8.py                          # Validate issue #8 Phase 1 (scorer)
```

## Conventions

- **Job IDs**: `org-name--role-title--YYYY-MM` (lowercase, hyphens, double-dash separators)
- **Org IDs**: `org-name` (lowercase, hyphens)
- All JSON validated against schemas in `schemas/`
- `confidence` < 1.0 for auto-parsed records, 1.0 for manual and structured sources (80K Hours)

## Key Patterns

- Git is the primary data store; Airtable is a browsable view
- Each job/org is a separate JSON file (not batched)
- Schemas use Draft-07 (`jsonschema.Draft7Validator`)
- Claude Code skill lives at `Skills/ea-jobs-db/SKILL.md` in agent-system repo (symlinked to `~/.claude/skills/ea-jobs-db`)
- `bulk_upload.py` denormalizes org info + JD content into Airtable records (batched, rate-limited)

## Gotchas

- No CI configured yet — no GitHub Actions workflows
- No npm/node setup — this is a Python + JSON project
- `jsonschema` must be installed (`pip3 install jsonschema`) before running tests
- Airtable integration is Tier 2 (warning only, not blocking)
- macOS `find` is aliased to `fd` — use shell loops for file operations
- Job schema requires `date_added` field — parser sets it to today's date
- Parser must merge with existing org files, not overwrite (preserves manual data)
- Slack export path must be configured before parser can run on real data
- `slugify()` must strip commas (e.g. "80,000 Hours" → "80000-hours")
- Job schema uses `additionalProperties: false` — adding new fields (e.g. `jd_status`) requires schema update
- JD files use YAML frontmatter (job_id, source_url, fetched_date, platform)
- YAML frontmatter: NEVER use `content.index("---", 3)` to find end delimiter — URLs can contain `---` (Workday). Use line-based detection instead
- `build_frontmatter()` quotes source_url when it contains `---`
- stdlib `urllib.request` + `html.parser` used for fetching/parsing — no external deps needed for JD fetcher
- Airtable sync uses env vars: AIRTABLE_API_KEY, AIRTABLE_BASE_ID (required for live sync)
- Airtable multi-select fields require `[{"name": "value"}]` format, not plain arrays
- Sync script logs to stderr, JSON output to stdout — keeps --output-json clean
- Algolia search-only keys can't use `browse_objects` — use paginated `search_single_index` instead
- Algolia SDK v4 returns Pydantic models — use `.to_dict()` to get plain dicts
- 80K Hours data: `description_short` has HTML, `description` is usually empty
- Use `datetime.fromtimestamp(ts, tz=timezone.utc)` not `utcfromtimestamp()` (deprecated Python 3.12+)
- Issue #6 has a human review checkpoint (Phase 2) — merges cannot be auto-applied
- Test section name assertions are case-insensitive substring checks — ensure report headers contain expected keywords
- `rapidfuzz.fuzz.ratio` returns 0-100, divide by 100 for 0-1 range
- `jd_quality.py` scorer: 0-100 scale, promote (>=60), review (40-59), quarantine (<40 or fatal)
- Issue #8 is multi-phase: Phase 1 (scorer) done, Phase 2a (infrastructure) done, Phase 2b (run fetch) done, Phase 3 (code done, awaiting human review + Airtable sync)
- `fetch_jds.py --overwrite` writes to `data/jds-staging/`, not production; `--promote` triggers score+backup+promote
- Promotion only overwrites production if staged file body is longer than existing (prevents regression)
- Lever pages have ~700KB inline CSS with class names matching content patterns — ALWAYS strip before `</style>` before extracting
- Ashby/Workable are JS-rendered SPA — `urllib` gets empty shells, needs headless browser (out of scope)
- Google Docs URLs need `/pub` or `/export?format=html` suffix for content (default `/edit` returns UI chrome)
- Phase 2b results: 543 JDs overwritten with full content, 75 quarantined, 25 for review. Backup at `data/jds-backup/`
- `data/jds-staging/` and `data/jds-backup/` are gitignored (working data only)
