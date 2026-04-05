#!/usr/bin/env python3
"""
Process Google Maps saved-list CSVs into Second Brain knowledge graph.
Creates one Artifact per CSV file, with MENTIONS edges to known projects/concepts.
"""
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import uuid as uuid_mod
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import cfg


def load_projects_config():
    config_path = Path(__file__).parent.parent / "projects.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"projects": {}, "concept_keywords": {}, "location_rules": {}, "notebook_mappings": {}}


_config = load_projects_config()

MAPS_DIR = os.path.join(cfg.BRAIN_INBOX, "maps")
PROCESSED_DIR = os.path.join(cfg.BRAIN_INBOX, "processed")
EXTRACTIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "extractions", "maps")
GRAPH_WRITER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graph_writer.py")
PYTHON = sys.executable

# Load location-based matching rules from config
LOCATION_RULES = {k: v for k, v in _config.get("location_rules", {}).items() if k != "_comment"}


def sanitize(text):
    """Remove apostrophes and other problematic chars for SQL safety."""
    if text is None:
        return ""
    return str(text).replace("'", "").replace('"', "").replace("\\", "")


def slugify(name):
    """Create a URL-safe slug from a name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


def read_csv(filepath):
    """Read a Google Maps CSV, return list of place titles (non-empty)."""
    places = []
    try:
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = (row.get("Title") or "").strip()
                if title:
                    places.append(title)
    except Exception as e:
        print(f"  ERROR reading {filepath}: {e}")
    return places


def build_extraction(csv_filename, places):
    """Build an extraction dict for one CSV file."""
    list_name = sanitize(os.path.splitext(csv_filename)[0])
    slug = slugify(csv_filename.replace(".csv", ""))
    row_count = len(places)

    safe_places = [sanitize(p) for p in places]
    sample = safe_places[:5]
    sample_str = ", ".join(sample[:3]) if sample else "none"

    summary = (
        f"Google Maps saved list: {list_name}. "
        f"{row_count} places saved. "
        f"Locations include: {sample_str}"
    )
    if len(summary) > 500:
        summary = summary[:497] + "..."

    artifact = {
        "name": list_name,
        "source_type": "maps",
        "source_path": f"brain-inbox/maps/{csv_filename}",
        "content_hash": f"maps-{slug}",
        "summary": summary,
        "metadata": {
            "place_count": row_count,
            "sample_places": sample,
        },
    }

    edges = []
    name_lower = list_name.lower()
    matched_targets = set()

    for keyword, rule_info in LOCATION_RULES.items():
        if keyword in name_lower:
            target_key = (rule_info["to_type"], rule_info["to_name"])
            if target_key not in matched_targets:
                matched_targets.add(target_key)
                context = rule_info.get("context", f"Maps saved list - {list_name}")
                edges.append({
                    "type": "MENTIONS",
                    "from_type": "Artifact",
                    "from_name": list_name,
                    "to_type": rule_info["to_type"],
                    "to_name": rule_info["to_name"],
                    "properties": {"context": sanitize(context)},
                })

    return {
        "artifact": artifact,
        "projects": [],
        "concepts": [],
        "decisions": [],
        "persons": [],
        "edges": edges,
    }


def main():
    os.makedirs(EXTRACTIONS_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    all_files = sorted(os.listdir(MAPS_DIR))
    csv_files = [f for f in all_files if f.lower().endswith(".csv")]
    json_files = [f for f in all_files if f.lower().endswith(".json")]

    print(f"Found {len(csv_files)} CSV files and {len(json_files)} JSON files")
    print(f"Skipping JSON files (too large / different format)")
    print()

    total_artifacts = 0
    total_edges = 0
    total_errors = 0
    total_places = 0

    for csv_file in csv_files:
        csv_path = os.path.join(MAPS_DIR, csv_file)
        print(f"Processing: {csv_file}")

        places = read_csv(csv_path)
        total_places += len(places)

        if len(places) == 0:
            print(f"  WARN: No places found in {csv_file}, creating artifact anyway")

        extraction = build_extraction(csv_file, places)

        ext_id = str(uuid_mod.uuid4())
        ext_path = os.path.join(EXTRACTIONS_DIR, f"{ext_id}.json")
        with open(ext_path, "w", encoding="utf-8") as f:
            json.dump(extraction, f, indent=2, ensure_ascii=False)

        try:
            result = subprocess.run(
                [PYTHON, GRAPH_WRITER, ext_path],
                capture_output=True, text=True, timeout=30,
            )
            print(result.stdout.strip())
            if result.stderr.strip():
                print(f"  STDERR: {result.stderr.strip()}")
            if result.returncode != 0:
                total_errors += 1
                print(f"  ERROR: graph_writer returned {result.returncode}")
            else:
                total_artifacts += 1
                total_edges += len(extraction["edges"])
        except Exception as e:
            total_errors += 1
            print(f"  ERROR running graph_writer: {e}")

        dest = os.path.join(PROCESSED_DIR, csv_file)
        if os.path.exists(dest):
            base, ext = os.path.splitext(csv_file)
            dest = os.path.join(PROCESSED_DIR, f"{base}_maps{ext}")
        try:
            shutil.move(csv_path, dest)
            print(f"  Moved to processed/")
        except Exception as e:
            print(f"  ERROR moving file: {e}")
            total_errors += 1

    for json_file in json_files:
        json_path = os.path.join(MAPS_DIR, json_file)
        dest = os.path.join(PROCESSED_DIR, json_file)
        if os.path.exists(dest):
            base, ext = os.path.splitext(json_file)
            dest = os.path.join(PROCESSED_DIR, f"{base}_maps{ext}")
        try:
            shutil.move(json_path, dest)
            print(f"Moved JSON {json_file} to processed/ (skipped processing)")
        except Exception as e:
            print(f"ERROR moving JSON {json_file}: {e}")
            total_errors += 1

    print()
    print("=" * 60)
    print(f"SUMMARY")
    print(f"  CSVs processed:    {len(csv_files)}")
    print(f"  Artifacts created: {total_artifacts}")
    print(f"  Edges created:     {total_edges}")
    print(f"  Total places:      {total_places}")
    print(f"  Errors:            {total_errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()
