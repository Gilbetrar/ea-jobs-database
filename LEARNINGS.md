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
python3 scripts/test_issue_1.py   # Validate schemas, samples, docs
pip3 install jsonschema            # Required dependency
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
