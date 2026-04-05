#!/usr/bin/env python3
"""
Fix orphan Concept nodes in ArcadeDB Second Brain graph.
Orphan = no edges at all (both().size() = 0).

Strategy:
1. Find all orphan concepts
2. Try to link each to existing Artifact (MENTIONS), Project (PART_OF), or Concept (RELATES_TO)
3. Delete remaining orphans that have no description (extraction noise)
4. Keep orphans with descriptions (may be useful later)
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import cfg


def query(sql):
    try:
        return cfg.arcadedb_query(sql)
    except Exception as e:
        return []


def execute(sql):
    return cfg.arcadedb_execute(sql)


def safe_sql(s):
    """Escape a string for SQL: double single-quotes, remove backslashes."""
    if s is None:
        return ""
    return s.replace("\\", "\\\\").replace("'", "\\'")


def main():
    print("=" * 60)
    print("ORPHAN CONCEPT FIXER")
    print("=" * 60)

    # Step 1: Find all orphan concepts
    print("\n[1] Querying orphan Concept nodes...")
    orphans = query("SELECT @rid, name, description, source FROM Concept WHERE both().size() = 0")
    print(f"    Found {len(orphans)} orphan concepts")

    if not orphans:
        print("    Nothing to do!")
        return

    for o in orphans:
        desc = o.get("description", "") or ""
        print(f"    - {o.get('name', '?'):<40} desc={'yes' if desc.strip() else 'no'}")

    # Step 2: Load existing artifacts, projects, and concepts for matching
    print("\n[2] Loading existing nodes for matching...")
    artifacts = query("SELECT @rid, name, summary FROM Artifact")
    projects = query("SELECT @rid, name FROM Project")
    all_concepts = query("SELECT @rid, name FROM Concept")
    print(f"    Artifacts: {len(artifacts)}, Projects: {len(projects)}, Concepts: {len(all_concepts)}")

    orphan_names = {o.get("name", "") for o in orphans}

    edges_created = 0
    linked_orphans = set()

    # Step 3a: Check if any Artifact name/summary contains the orphan concept name
    print("\n[3a] Checking Artifact matches (MENTIONS edges)...")
    for orphan in orphans:
        oname = orphan.get("name", "")
        if not oname or len(oname) < 3:
            continue

        oname_lower = oname.lower()
        for art in artifacts:
            art_name = (art.get("name", "") or "").lower()
            art_summary = (art.get("summary", "") or "").lower()

            if oname_lower in art_name or oname_lower in art_summary:
                art_safe = safe_sql(art.get("name", ""))
                oname_safe = safe_sql(oname)
                sql = (
                    f"CREATE EDGE MENTIONS FROM "
                    f"(SELECT FROM Artifact WHERE name = '{art_safe}' LIMIT 1) TO "
                    f"(SELECT FROM Concept WHERE name = '{oname_safe}' LIMIT 1) "
                    f"SET context = 'auto-linked orphan fix'"
                )
                try:
                    execute(sql)
                    edges_created += 1
                    linked_orphans.add(oname)
                    print(f"    MENTIONS: Artifact[{art.get('name', '')}] -> Concept[{oname}]")
                except Exception as e:
                    print(f"    ERROR creating MENTIONS edge: {e}")
                break

    # Step 3b: Check if concept name matches a known project name
    print("\n[3b] Checking Project matches (PART_OF edges)...")
    project_names_lower = {p.get("name", "").lower(): p.get("name", "") for p in projects}

    for orphan in orphans:
        oname = orphan.get("name", "")
        if not oname or len(oname) < 3:
            continue

        oname_lower = oname.lower()
        for pname_lower, pname in project_names_lower.items():
            if not pname_lower:
                continue
            if (oname_lower in pname_lower or pname_lower in oname_lower) and oname_lower != pname_lower:
                oname_safe = safe_sql(oname)
                pname_safe = safe_sql(pname)
                sql = (
                    f"CREATE EDGE PART_OF FROM "
                    f"(SELECT FROM Concept WHERE name = '{oname_safe}' LIMIT 1) TO "
                    f"(SELECT FROM Project WHERE name = '{pname_safe}' LIMIT 1) "
                    f"SET role = 'auto-linked orphan fix'"
                )
                try:
                    execute(sql)
                    edges_created += 1
                    linked_orphans.add(oname)
                    print(f"    PART_OF: Concept[{oname}] -> Project[{pname}]")
                except Exception as e:
                    print(f"    ERROR creating PART_OF edge: {e}")
                break

    # Step 3c: Check if any other Concept has a similar name (substring)
    print("\n[3c] Checking Concept-to-Concept matches (RELATES_TO edges)...")
    non_orphan_concepts = [c for c in all_concepts if c.get("name", "") not in orphan_names]

    for orphan in orphans:
        oname = orphan.get("name", "")
        if not oname or len(oname) < 4:
            continue
        if oname in linked_orphans:
            continue

        oname_lower = oname.lower()
        for other in non_orphan_concepts:
            other_name = other.get("name", "")
            other_lower = other_name.lower()
            if not other_lower or other_lower == oname_lower:
                continue

            if (len(oname_lower) >= 4 and oname_lower in other_lower) or \
               (len(other_lower) >= 4 and other_lower in oname_lower):
                oname_safe = safe_sql(oname)
                other_safe = safe_sql(other_name)
                sql = (
                    f"CREATE EDGE RELATES_TO FROM "
                    f"(SELECT FROM Concept WHERE name = '{oname_safe}' LIMIT 1) TO "
                    f"(SELECT FROM Concept WHERE name = '{other_safe}' LIMIT 1) "
                    f"SET label = 'related_to', context = 'auto-linked orphan fix'"
                )
                try:
                    execute(sql)
                    edges_created += 1
                    linked_orphans.add(oname)
                    print(f"    RELATES_TO: Concept[{oname}] -> Concept[{other_name}]")
                except Exception as e:
                    print(f"    ERROR creating RELATES_TO edge: {e}")
                break

    # Step 4: Re-check orphans
    print("\n[4] Re-checking orphan status...")
    still_orphans = query("SELECT @rid, name, description, source FROM Concept WHERE both().size() = 0")
    print(f"    Still orphaned: {len(still_orphans)}")

    # Step 5: Delete orphans with no description
    deleted = 0
    kept = 0
    print("\n[5] Cleaning up description-less orphans...")
    for orphan in still_orphans:
        oname = orphan.get("name", "")
        desc = orphan.get("description", "") or ""
        if not desc.strip():
            oname_safe = safe_sql(oname)
            sql = f"DELETE FROM Concept WHERE name = '{oname_safe}' AND both().size() = 0"
            try:
                execute(sql)
                deleted += 1
                print(f"    DELETED: {oname}")
            except Exception as e:
                print(f"    ERROR deleting {oname}: {e}")
        else:
            kept += 1
            print(f"    KEPT (has description): {oname}")

    final_orphans = query("SELECT name FROM Concept WHERE both().size() = 0")
    print("\n" + "=" * 60)
    print("REPORT")
    print("=" * 60)
    print(f"  Orphans before:     {len(orphans)}")
    print(f"  Edges created:      {edges_created}")
    print(f"  Orphans linked:     {len(linked_orphans)}")
    print(f"  Orphans deleted:    {deleted}")
    print(f"  Orphans kept:       {kept}")
    print(f"  Orphans remaining:  {len(final_orphans)}")
    if final_orphans:
        print("  Remaining orphans (with descriptions, kept for future use):")
        for o in final_orphans:
            print(f"    - {o.get('name', '?')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
