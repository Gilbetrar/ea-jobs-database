# Agent Instructions — EA Jobs Database

## Workflow

1. Check open issues: `gh issue list --state open`
2. Read the issue fully before starting work
3. Read LEARNINGS.md for project patterns and gotchas
4. Make changes, validate, commit, push
5. Update SESSION_LOG.md with what you learned

## Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `scripts/test_issue_1.py` | Validate repo setup and schemas | `python scripts/test_issue_1.py` |

Scripts are Python 3. Install dependencies:

```bash
pip install jsonschema
```

## Data Locations

| Data | Location | Format |
|------|----------|--------|
| Job postings | `data/jobs/` | JSON (one file per job) |
| Organizations | `data/orgs/` | JSON (one file per org) |
| Job descriptions | `data/jds/` | Markdown |
| JSON Schemas | `schemas/` | JSON Schema Draft-07 |
| Generated exports | `exports/` | CSV, reports |

## Conventions

### File Naming

- **Job files**: `{org-id}--{role-slug}--{YYYY-MM}.json`
- **Org files**: `{org-id}.json`
- **JD files**: `{job-id}.md`

All identifiers use lowercase with hyphens. Double-dash (`--`) separates the three components of a job ID.

### Schema Compliance

All job and org JSON files MUST validate against their respective schemas in `schemas/`. Use `jsonschema.validate()` to check.

### Git Conventions

- Commit messages reference issue numbers: `feat: description (#N)`
- One JSON file per job posting — never batch multiple jobs into one file
- Keep data files clean — no comments, consistent formatting

### Adding New Data Sources

When adding a new ingestion source:
1. Create a parser script in `scripts/`
2. Set the `source` field appropriately in generated records
3. Set `confidence` < 1.0 for auto-parsed records
4. Add the source to the README.md data sources table
