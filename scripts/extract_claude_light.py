#!/usr/bin/env python3
"""
Extract LIGHT-classified Claude conversations into knowledge graph.
Creates one Artifact node per conversation with MENTIONS edges to known projects.
"""
import json
import os
import sys
import subprocess
import shutil
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

LIGHT_DIR = os.path.join(cfg.BRAIN_INBOX, "classified", "light")
PROCESSED_DIR = os.path.join(cfg.BRAIN_INBOX, "processed")
EXTRACTIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "extractions", "claude-light")
GRAPH_WRITER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graph_writer.py")
PYTHON = sys.executable

# Build project list and alias mapping from config
KNOWN_PROJECTS = list(_config.get("projects", {}).keys())

PROJECT_ALIASES = {}
for proj_name, proj_info in _config.get("projects", {}).items():
    for alias in proj_info.get("aliases", []):
        PROJECT_ALIASES[alias] = proj_name


def strip_apostrophes(s):
    """Remove all apostrophes from a string - SQL parser breaks on them."""
    if s is None:
        return ""
    return str(s).replace("'", "").replace("\u2019", "").replace("\u2018", "")


def get_first_human_message(messages):
    """Extract the first human message text."""
    for msg in messages:
        if msg.get("sender") == "human":
            text = msg.get("text", "")
            if text:
                return strip_apostrophes(text[:500])
    return ""


def find_project_mentions(text):
    """Find known projects mentioned in text."""
    lower = text.lower()
    found = set()
    for alias, project in PROJECT_ALIASES.items():
        if alias in lower:
            found.add(project)
    return list(found)


def make_summary(title, first_msg):
    """Create a brief summary from title and first message."""
    if first_msg:
        snippet = first_msg[:150].strip()
        if len(first_msg) > 150:
            snippet += "..."
        return strip_apostrophes(f"{title}: {snippet}")
    return strip_apostrophes(title)


def process_file(filepath):
    """Process one conversation JSON file into an extraction."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    uuid = data.get("uuid", "")
    name = strip_apostrophes(data.get("name", "")) or "Untitled"
    created_at = data.get("created_at", "")
    messages = data.get("chat_messages", [])
    msg_count = len(messages)
    first_msg = get_first_human_message(messages)

    summary = make_summary(name, first_msg)

    search_text = f"{name} {first_msg}"
    projects = find_project_mentions(search_text)

    edges = []
    for proj in projects:
        edges.append({
            "type": "MENTIONS",
            "from_type": "Artifact",
            "from_name": name,
            "to_type": "Project",
            "to_name": proj,
            "properties": {"context": "referenced in claude conversation"}
        })

    extraction = {
        "artifact": {
            "name": name,
            "source_type": "claude",
            "source_path": f"brain-inbox/claude/{uuid}.json",
            "content_hash": f"claude-{uuid}",
            "summary": summary,
            "source_timestamp": created_at,
            "metadata": {
                "uuid": uuid,
                "message_count": msg_count,
                "triage": "light"
            }
        },
        "concepts": [],
        "decisions": [],
        "projects": [],
        "persons": [],
        "edges": edges
    }

    return extraction, name, len(edges)


def main():
    os.makedirs(EXTRACTIONS_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    files = sorted([
        f for f in os.listdir(LIGHT_DIR) if f.endswith(".json")
    ])
    print(f"Found {len(files)} files to process")

    test_mode = "--test" in sys.argv
    if test_mode:
        files = files[:2]
        print(f"TEST MODE: processing first {len(files)} files only")

    total_artifacts = 0
    total_edges = 0
    total_errors = 0

    for i, fname in enumerate(files, 1):
        filepath = os.path.join(LIGHT_DIR, fname)
        try:
            extraction, name, edge_count = process_file(filepath)

            ext_path = os.path.join(EXTRACTIONS_DIR, fname)
            with open(ext_path, "w", encoding="utf-8") as f:
                json.dump(extraction, f, indent=2, ensure_ascii=False)

            result = subprocess.run(
                [PYTHON, GRAPH_WRITER, ext_path],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                print(f"[{i}/{len(files)}] ERROR graph_writer on {name}: {result.stderr[:200]}")
                total_errors += 1
            else:
                print(f"[{i}/{len(files)}] OK: {name} ({edge_count} edges)")
                if result.stdout.strip():
                    for line in result.stdout.strip().split("\n"):
                        print(f"    {line}")
                total_artifacts += 1
                total_edges += edge_count

                dest = os.path.join(PROCESSED_DIR, fname)
                shutil.move(filepath, dest)

        except Exception as e:
            print(f"[{i}/{len(files)}] EXCEPTION on {fname}: {e}")
            total_errors += 1

    print(f"\n{'='*60}")
    print(f"TOTALS:")
    print(f"  Files processed: {total_artifacts + total_errors}")
    print(f"  Artifacts created: {total_artifacts}")
    print(f"  Edges created: {total_edges}")
    print(f"  Errors: {total_errors}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
