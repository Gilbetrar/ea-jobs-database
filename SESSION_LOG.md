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
