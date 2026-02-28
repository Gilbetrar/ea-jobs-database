# EA Jobs Database

Historical database of effective altruism (EA) job opportunities for salary and role comparables.

## Overview

This project collects and organizes job postings from the EA community into a structured, searchable database. The primary goal is to provide historical salary and role data for compensation benchmarking and career research.

## Architecture

- **Git repository** is the primary data store — no record limits, full version history
- **Airtable** serves as a curated browsable view (free tier, limited to 1,000 records)
- Each job posting is stored as an individual JSON file validated against a JSON Schema
- Organizations are tracked separately and linked to jobs via ID references

### Data Flow

```
Sources (Slack, 80K Hours, Manual)
        ↓
  Parsing Scripts
        ↓
  data/jobs/*.json  +  data/orgs/*.json
        ↓
  Airtable Sync Script
        ↓
  Airtable (browsable view)
```

### Directory Structure

```
ea-jobs-database/
├── data/
│   ├── jobs/           # One JSON file per job posting
│   ├── orgs/           # One JSON file per organization
│   └── jds/            # Full job descriptions as markdown
├── scripts/            # Python parsing/syncing scripts
├── schemas/            # JSON Schema definitions
├── exports/            # Generated reports, CSVs
├── README.md
└── AGENTS.md
```

## Data Sources

| Source | Method | Status |
|--------|--------|--------|
| EA Slack #jobs channel | Parse Slack export JSON | Planned (#2) |
| 80,000 Hours job board | Algolia API ingestion | Planned (#5) |
| Manual entry | Direct JSON creation | Available now |

## How to Contribute

### Adding a Job Manually

1. Create a new JSON file in `data/jobs/` following the naming convention: `org-name--role-title--YYYY-MM.json`
2. Fill in the fields according to `schemas/job.schema.json`
3. If the organization doesn't exist yet, create it in `data/orgs/`
4. Optionally save the full job description as markdown in `data/jds/`
5. Validate your files: `python scripts/validate.py`

### ID Conventions

- **Job IDs**: `org-name--role-title--YYYY-MM` (lowercase, hyphens, double-dash separator)
- **Org IDs**: `org-name` (lowercase, hyphens only)
- **JD filenames**: Match the job ID with `.md` extension

### Validation

All JSON files are validated against their schemas. Run:

```bash
python scripts/test_issue_1.py
```
