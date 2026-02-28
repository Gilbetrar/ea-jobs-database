#!/usr/bin/env python3
"""Test script for Issue #7: Claude Code Skill for Ongoing Adds.

Validates structural requirements of the ea-jobs-db skill.
Workflow testing (URL add, conversation add, 80K refresh, status) requires
manual testing — see issue #7 verification section.

Exit code 0 = pass, non-zero = fail.
"""

import os
import sys
import json
import glob

passed = 0
failed = 0
warnings = 0

def test_pass(msg):
    global passed
    passed += 1
    print(f"  PASS: {msg}")

def test_fail(msg):
    global failed
    failed += 1
    print(f"  FAIL: {msg}")

def test_warn(msg):
    global warnings
    warnings += 1
    print(f"  WARNING: {msg}")


# === Tier 1: Structural Checks ===

print("=== Tier 1: Structural Checks ===\n")

# 1. SKILL.md exists and has valid YAML frontmatter
skill_path = os.path.expanduser('~/AI/Agents/Skills/ea-jobs-db/SKILL.md')
if os.path.isfile(skill_path):
    test_pass("SKILL.md exists")
else:
    test_fail(f"Missing SKILL.md at {skill_path}")
    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed, {warnings} warnings")
    print(f"OVERALL: {'PASS' if failed == 0 else 'FAIL'}")
    sys.exit(1)

content = open(skill_path).read()
if content.startswith('---'):
    test_pass("SKILL.md has YAML frontmatter delimiter")
else:
    test_fail("SKILL.md missing YAML frontmatter")
    sys.exit(1)

# Parse frontmatter
try:
    fm_end = content.index('---', 3)
    fm_text = content[3:fm_end]
    # Use simple parsing since yaml might not be installed
    # Check for required fields as plain text
    has_name = 'name:' in fm_text
    has_description = 'description:' in fm_text
    has_triggers = 'triggers:' in fm_text

    if has_name:
        test_pass("Frontmatter has 'name' field")
    else:
        test_fail("Frontmatter missing 'name' field")

    if has_description:
        test_pass("Frontmatter has 'description' field")
    else:
        test_fail("Frontmatter missing 'description' field")

    if has_triggers:
        test_pass("Frontmatter has 'triggers' field")
    else:
        test_fail("Frontmatter missing 'triggers' field")
except ValueError:
    test_fail("Could not find closing YAML frontmatter delimiter")

# 2. Trigger patterns don't overlap with job-search skill
job_search_path = os.path.expanduser('~/AI/Agents/Skills/job-search/SKILL.md')
if os.path.isfile(job_search_path):
    js_content = open(job_search_path).read()
    try:
        js_fm_end = js_content.index('---', 3)
        js_fm_text = js_content[3:js_fm_end]

        # Extract trigger lines from both skills
        def extract_triggers(text):
            triggers = set()
            in_triggers = False
            for line in text.split('\n'):
                stripped = line.strip()
                if stripped.startswith('triggers:'):
                    in_triggers = True
                    continue
                if in_triggers:
                    if stripped.startswith('- '):
                        trigger = stripped[2:].strip().strip('"').strip("'")
                        triggers.add(trigger.lower())
                    elif stripped and not stripped.startswith('-'):
                        in_triggers = False
            return triggers

        js_triggers = extract_triggers(js_fm_text)
        ea_triggers = extract_triggers(fm_text)
        overlap = js_triggers & ea_triggers

        if not overlap:
            test_pass("No trigger overlap with job-search skill")
        else:
            test_fail(f"Trigger overlap with job-search skill: {overlap}")
    except ValueError:
        test_warn("Could not parse job-search frontmatter for trigger comparison")
else:
    test_warn("job-search SKILL.md not found — skipping trigger overlap check")

# 3. All referenced script paths exist
ea_db_repo = os.path.expanduser('~/AI/Projects/ea-jobs-database')
required_scripts = [
    'scripts/fetch_80k_hours.py',
    'scripts/sync_to_airtable.py',
]
for script in required_scripts:
    full_path = os.path.join(ea_db_repo, script)
    if os.path.isfile(full_path):
        test_pass(f"Referenced script exists: {script}")
    else:
        test_fail(f"Referenced script missing: {full_path}")

# 4. Symlink from ~/.claude/skills/ea-jobs-db/ points to correct location
symlink_path = os.path.expanduser('~/.claude/skills/ea-jobs-db')
if os.path.islink(symlink_path):
    target = os.path.realpath(symlink_path)
    expected = os.path.realpath(os.path.expanduser('~/AI/Agents/Skills/ea-jobs-db'))
    if target == expected:
        test_pass("Symlink points to correct location")
    else:
        test_fail(f"Symlink points to {target}, expected {expected}")
elif os.path.isdir(symlink_path):
    test_warn("ea-jobs-db exists at ~/.claude/skills/ but is not a symlink")
else:
    test_fail(f"Missing symlink at {symlink_path}")

# 5. Skill content covers all four workflows
skill_body = content.lower()
workflows = [
    ('workflow 1', 'add job from url'),
    ('workflow 2', 'add job from conversation'),
    ('workflow 3', 'refresh 80k hours'),
    ('workflow 4', 'database status'),
]
for wf_name, wf_desc in workflows:
    if wf_desc in skill_body or wf_name in skill_body:
        test_pass(f"Skill covers: {wf_desc}")
    else:
        test_fail(f"Skill missing workflow: {wf_desc}")

# 6. Skill references correct schemas
schema_files = ['schemas/job.schema.json', 'schemas/org.schema.json']
for sf in schema_files:
    if sf in content:
        test_pass(f"Skill references {sf}")
    else:
        test_warn(f"Skill doesn't explicitly reference {sf}")

# 7. Skill mentions validation
if 'validate' in skill_body or 'jsonschema' in skill_body:
    test_pass("Skill includes schema validation guidance")
else:
    test_fail("Skill missing schema validation guidance")

# 8. Skill mentions Airtable sync as optional
if 'airtable' in skill_body:
    test_pass("Skill references Airtable sync")
else:
    test_warn("Skill doesn't mention Airtable sync")

# 9. Check skill name is distinct from job-search
if 'ea-jobs-db' in fm_text or 'ea-jobs' in fm_text:
    test_pass("Skill name is distinct from job-search")
else:
    test_fail("Skill name unclear or potentially overlapping")


print(f"\n{'='*40}")

# Manual testing notice
print("\n=== Manual Testing Required ===\n")
print("  I cannot verify these workflows automatically.")
print("  The test script covers structural checks only.")
print("  Manual testing of the following phrases is required:\n")
print('  Workflow 1: "Add this to the EA jobs database: https://example.com/job"')
print('  Workflow 2: "Save this EA job: Open Phil is hiring a Research Analyst"')
print('  Workflow 3: "Refresh the 80K Hours data in the EA jobs database"')
print('  Workflow 4: "How many jobs are in the EA database?"')
print('  Non-activation: "Add a job to my tracker" (should NOT trigger ea-jobs-db)')
print('  Non-activation: "Update my job search CRM" (should NOT trigger ea-jobs-db)')

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed, {warnings} warnings")
print(f"OVERALL: {'PASS' if failed == 0 else 'FAIL'}")
sys.exit(0 if failed == 0 else 1)
