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
pip3 install jsonschema                                  # Required dependency
```

## Conventions

- **Job IDs**: `org-name--role-title--YYYY-MM` (lowercase, hyphens, double-dash separators)
- **Org IDs**: `org-name` (lowercase, hyphens)
- All JSON validated against schemas in `schemas/`
- `confidence` < 1.0 for auto-parsed records, 1.0 for manual

## Key Patterns

- Git is the primary data store; Airtable is a browsable view
- Each job/org is a separate JSON file (not batched)
- Schemas use Draft-07 (`jsonschema.Draft7Validator`)

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
- stdlib `urllib.request` + `html.parser` used for fetching/parsing — no external deps needed for JD fetcher
