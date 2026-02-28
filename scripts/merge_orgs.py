#!/usr/bin/env python3
"""
Org canonicalization and merge script for EA Jobs Database.

Detects duplicate orgs via fuzzy matching and proposes merges.
Generates exports/proposed-merges.json for human review.
With --apply, merges orgs and updates all job references.

Usage:
    python3 scripts/merge_orgs.py              # Generate proposed merges
    python3 scripts/merge_orgs.py --apply      # Apply approved merges
    python3 scripts/merge_orgs.py --threshold 0.80  # Custom similarity threshold
"""

import argparse
import json
import glob
import os
import sys

from rapidfuzz import fuzz


# Known canonical mappings (org ID → list of alias org IDs)
KNOWN_ALIASES = {
    "centre-for-effective-altruism": [
        "cea",
        "center-for-effective-altruism",
    ],
    "open-philanthropy": ["open-phil", "openphil"],
    "givewell": ["give-well"],
    "80000-hours": ["80k-hours", "eighty-thousand-hours"],
    "rethink-priorities": ["rethink"],
    "animal-charity-evaluators": ["ace"],
}


def load_orgs():
    """Load all org records as a dict keyed by ID."""
    orgs = {}
    for f in sorted(glob.glob("data/orgs/*.json")):
        with open(f) as fh:
            org = json.load(fh)
            orgs[org["id"]] = org
    return orgs


def load_jobs():
    """Load all job records."""
    jobs = []
    for f in sorted(glob.glob("data/jobs/*.json")):
        with open(f) as fh:
            jobs.append(json.load(fh))
    return jobs


def get_all_names(org):
    """Get all names for an org (name + aliases)."""
    names = [org["name"]]
    names.extend(org.get("aliases", []))
    return names


def find_proposed_merges(orgs, threshold=0.85):
    """Find pairs of orgs that are likely duplicates."""
    proposals = []
    seen_pairs = set()
    org_list = list(orgs.values())

    # First: check known aliases
    for canonical_id, alias_ids in KNOWN_ALIASES.items():
        for alias_id in alias_ids:
            if alias_id in orgs and canonical_id in orgs:
                pair_key = tuple(sorted([canonical_id, alias_id]))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    proposals.append(
                        {
                            "canonical_id": canonical_id,
                            "canonical_name": orgs[canonical_id]["name"],
                            "merge_id": alias_id,
                            "merge_name": orgs[alias_id]["name"],
                            "confidence": 1.0,
                            "reason": "known alias",
                        }
                    )

    # Second: fuzzy matching on all org names
    for i, org1 in enumerate(org_list):
        names1 = get_all_names(org1)
        for org2 in org_list[i + 1 :]:
            pair_key = tuple(sorted([org1["id"], org2["id"]]))
            if pair_key in seen_pairs:
                continue

            names2 = get_all_names(org2)

            # Compare all name combinations
            best_sim = 0
            best_pair = ("", "")
            for n1 in names1:
                for n2 in names2:
                    sim = fuzz.ratio(n1.lower(), n2.lower()) / 100
                    if sim > best_sim:
                        best_sim = sim
                        best_pair = (n1, n2)

            if best_sim >= threshold:
                seen_pairs.add(pair_key)
                # Pick the one with more data as canonical
                score1 = _org_richness(org1)
                score2 = _org_richness(org2)
                if score1 >= score2:
                    canonical, merge = org1, org2
                else:
                    canonical, merge = org2, org1

                proposals.append(
                    {
                        "canonical_id": canonical["id"],
                        "canonical_name": canonical["name"],
                        "merge_id": merge["id"],
                        "merge_name": merge["name"],
                        "confidence": round(best_sim, 3),
                        "reason": f"fuzzy match: '{best_pair[0]}' ≈ '{best_pair[1]}'",
                    }
                )

    # Sort by confidence descending
    proposals.sort(key=lambda x: x["confidence"], reverse=True)
    return proposals


def _org_richness(org):
    """Score how much data an org record has (for picking canonical)."""
    score = 0
    if org.get("website"):
        score += 2
    if org.get("cause_areas"):
        score += len(org["cause_areas"])
    if org.get("aliases"):
        score += len(org["aliases"])
    if org.get("hq_location"):
        score += 1
    if org.get("size_estimate"):
        score += 1
    if org.get("notes"):
        score += 1
    return score


def apply_merges(merges_file):
    """Apply approved merges: update org records and job references."""
    with open(merges_file) as f:
        merges = json.load(f)

    orgs = load_orgs()
    jobs = load_jobs()

    applied = 0
    for merge in merges:
        canonical_id = merge["canonical_id"]
        merge_id = merge["merge_id"]

        if canonical_id not in orgs:
            print(f"WARNING: Canonical org {canonical_id} not found, skipping",
                  file=sys.stderr)
            continue
        if merge_id not in orgs:
            print(f"WARNING: Merge org {merge_id} not found, skipping",
                  file=sys.stderr)
            continue

        canonical = orgs[canonical_id]
        to_merge = orgs[merge_id]

        # Merge aliases
        existing_aliases = set(canonical.get("aliases", []))
        existing_aliases.add(to_merge["name"])
        for alias in to_merge.get("aliases", []):
            existing_aliases.add(alias)
        # Don't include the canonical name itself as an alias
        existing_aliases.discard(canonical["name"])
        canonical["aliases"] = sorted(existing_aliases)

        # Merge other fields (keep canonical values, fill gaps)
        if not canonical.get("website") and to_merge.get("website"):
            canonical["website"] = to_merge["website"]
        if not canonical.get("hq_location") and to_merge.get("hq_location"):
            canonical["hq_location"] = to_merge["hq_location"]
        if not canonical.get("size_estimate") and to_merge.get("size_estimate"):
            canonical["size_estimate"] = to_merge["size_estimate"]
        if to_merge.get("cause_areas"):
            existing_causes = set(canonical.get("cause_areas", []))
            existing_causes.update(to_merge["cause_areas"])
            canonical["cause_areas"] = sorted(existing_causes)

        # Write updated canonical org
        with open(f"data/orgs/{canonical_id}.json", "w") as f:
            json.dump(canonical, f, indent=2)
            f.write("\n")

        # Update all job references
        jobs_updated = 0
        for job in jobs:
            if job.get("organization") == merge_id:
                job["organization"] = canonical_id

                # Update job ID to reflect new org
                old_id = job["id"]
                parts = old_id.split("--")
                parts[0] = canonical_id
                new_id = "--".join(parts)
                job["id"] = new_id

                # Write updated job (new filename)
                new_path = f"data/jobs/{new_id}.json"
                old_path = f"data/jobs/{old_id}.json"

                with open(new_path, "w") as f:
                    json.dump(job, f, indent=2)
                    f.write("\n")

                # Remove old file if ID changed
                if old_id != new_id and os.path.isfile(old_path):
                    os.remove(old_path)

                # Update JD file reference if needed
                if job.get("jd_file"):
                    old_jd = job["jd_file"]
                    new_jd = old_jd.replace(old_id, new_id)
                    if old_jd != new_jd and os.path.isfile(old_jd):
                        os.rename(old_jd, new_jd)
                    job["jd_file"] = new_jd
                    # Re-write with updated jd_file
                    with open(new_path, "w") as f:
                        json.dump(job, f, indent=2)
                        f.write("\n")

                jobs_updated += 1

        # Remove merged org file
        merge_path = f"data/orgs/{merge_id}.json"
        if os.path.isfile(merge_path):
            os.remove(merge_path)

        print(f"Merged '{to_merge['name']}' ({merge_id}) → "
              f"'{canonical['name']}' ({canonical_id}), "
              f"updated {jobs_updated} jobs")
        applied += 1

        # Remove merged org from our dict
        del orgs[merge_id]

    print(f"\nApplied {applied} merges total")
    return applied


def main():
    parser = argparse.ArgumentParser(
        description="Detect and merge duplicate organizations"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply merges from exports/proposed-merges.json",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Fuzzy match similarity threshold (default: 0.85)",
    )
    parser.add_argument(
        "--merges-file",
        default="exports/proposed-merges.json",
        help="Path to merges file (default: exports/proposed-merges.json)",
    )
    args = parser.parse_args()

    if args.apply:
        if not os.path.isfile(args.merges_file):
            print(f"ERROR: Merges file not found: {args.merges_file}", file=sys.stderr)
            sys.exit(1)
        apply_merges(args.merges_file)
        return

    # Generate proposed merges
    print("Loading orgs...", file=sys.stderr)
    orgs = load_orgs()
    print(f"Loaded {len(orgs)} orgs", file=sys.stderr)

    print(f"Finding duplicates (threshold: {args.threshold})...", file=sys.stderr)
    proposals = find_proposed_merges(orgs, args.threshold)

    os.makedirs("exports", exist_ok=True)
    with open(args.merges_file, "w") as f:
        json.dump(proposals, f, indent=2)
        f.write("\n")

    print(f"\nFound {len(proposals)} proposed merges", file=sys.stderr)
    print(f"Written to {args.merges_file}", file=sys.stderr)

    # Display summary
    if proposals:
        print("\nProposed merges:", file=sys.stderr)
        for p in proposals:
            conf_marker = " ⚠️ LOW" if p["confidence"] < 0.7 else ""
            print(
                f"  [{p['confidence']:.2f}]{conf_marker} "
                f"'{p['merge_name']}' → '{p['canonical_name']}' "
                f"({p['reason']})",
                file=sys.stderr,
            )
    else:
        print("\nNo duplicates found above threshold.", file=sys.stderr)


if __name__ == "__main__":
    main()
