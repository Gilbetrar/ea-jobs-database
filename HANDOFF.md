# Handoff: Issue #8 — Airtable JD Sync + Review Queue

## Status
- **Issue**: #8 - Re-fetch full job descriptions from source URLs
- **Branch**: main
- **Last commit**: a789552 chore: gitignore upload_batches.json, update fetch summary

## Action Required

Two human actions remain before issue #8 can be closed:

### 1. Review the borderline JD queue (25 items)

Open `exports/jd_review_queue.md` and skim the 25 borderline items. For each:
- If the JD looks real and useful → mark for promotion
- If it's garbage → leave quarantined

This calibrates thresholds for future fetches. No code changes needed — just Ben's judgment call.

### 2. Sync promoted JDs to Airtable

Run this command with the Airtable PAT:

```bash
cd ~/AI/Projects/ea-jobs-database
AIRTABLE_PAT=patXXX python3 scripts/bulk_upload.py --update-only --dry-run  # Preview first
AIRTABLE_PAT=patXXX python3 scripts/bulk_upload.py --update-only            # Then run for real
```

This patches the Job Description field on existing Airtable records with the full JD content (543 promoted files). Uses `git_id` to look up records.

The PAT is stored in Claude memory at `airtable-credentials.md`.

## Prepared Artifacts
- `exports/jd_review_queue.md` — Human-readable review queue (25 items)
- `exports/jd_review_queue.json` — Structured review queue data
- `exports/jd_quarantine.json` — Quarantined files manifest
- `exports/jd_refetch_report.json` — Full fetch report with per-platform stats
- `scripts/bulk_upload.py --update-only` — Ready to run Airtable sync

## Context
All code phases of issue #8 are complete:
- Phase 1: JD quality scorer (`jd_quality.py`)
- Phase 2: Fetch pipeline (543 JDs promoted, 75 quarantined, 25 for review)
- Phase 3: `--update-only` mode in bulk_upload.py + skill updated
- All 46 tests pass (`python3 scripts/test_issue_8.py`)

## After Completion
1. Run `python3 scripts/test_issue_8.py` to verify nothing broke
2. Close issue #8: `gh issue close 8 --repo Gilbetrar/ea-jobs-database`
3. **Delete this file**: `rm HANDOFF.md`

## Verification
The next autonomous agent can confirm completion by:
- Checking that issue #8 is closed
- Verifying Airtable records have Job Description field length > 500 chars (Tier 2 test in test_issue_8.py)
