#!/usr/bin/env python3
"""
Process Claude projects data for the Second Brain knowledge graph.
Reads projects.json, creates Artifact nodes per project, and MENTIONS edges
to known projects/concepts.
"""
import json
import os
import subprocess
import sys
import re
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

PYTHON = sys.executable
GRAPH_WRITER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graph_writer.py")
EXTRACTIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "extractions", "claude-projects")
SOURCE_FILE = os.path.join(cfg.BRAIN_INBOX, "claude-projects", "projects.json")
PROCESSED_DIR = os.path.join(cfg.BRAIN_INBOX, "processed")

# Build known projects dict (project name -> list of aliases) from config
KNOWN_PROJECTS = {}
for proj_name, proj_info in _config.get("projects", {}).items():
    KNOWN_PROJECTS[proj_name] = proj_info.get("aliases", [])


def sanitize(text):
    """Remove apostrophes and clean text for SQL safety."""
    if not text:
        return ""
    text = text.replace("'", "")
    text = text.replace("\u2019", "")
    text = text.replace("\u2018", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def make_summary(project):
    """Build a summary string from project name, description, and doc filenames."""
    parts = []
    desc = sanitize(project.get("description", ""))
    if desc:
        parts.append(desc)

    docs = project.get("docs", [])
    if docs:
        filenames = [sanitize(d.get("filename", "")) for d in docs]
        parts.append(f"Documents: {', '.join(filenames)}")

    prompt_tmpl = project.get("prompt_template", "")
    if prompt_tmpl:
        snippet = sanitize(prompt_tmpl[:200])
        parts.append(f"Prompt template: {snippet}")

    summary = ". ".join(parts)
    if len(summary) > 500:
        summary = summary[:497] + "..."
    return summary


def find_mentions(project):
    """Scan project for known project references."""
    text_parts = [
        project.get("name", ""),
        project.get("description", ""),
        project.get("prompt_template", ""),
    ]
    for doc in project.get("docs", []):
        text_parts.append(doc.get("filename", ""))
        content = doc.get("content", "")
        text_parts.append(content[:5000])

    search_text = " ".join(text_parts).lower()

    mentioned = []
    for proj_name, aliases in KNOWN_PROJECTS.items():
        for alias in aliases:
            if alias in search_text:
                mentioned.append(proj_name)
                break
    return mentioned


def build_extraction(project):
    """Build an extraction JSON dict for one Claude project."""
    uuid = project["uuid"]
    name = sanitize(project["name"])
    content_hash = f"claude-proj-{uuid}"
    summary = make_summary(project)
    created = project.get("created_at", "")
    updated = project.get("updated_at", "")
    creator_name = sanitize(project.get("creator", {}).get("full_name", ""))
    is_private = project.get("is_private", False)
    is_starter = project.get("is_starter_project", False)
    doc_count = len(project.get("docs", []))

    artifact = {
        "name": name,
        "source_type": "claude-project",
        "source_path": f"claude://projects/{uuid}",
        "content_hash": content_hash,
        "summary": summary,
        "source_timestamp": created[:19] if created else "",
        "metadata": {
            "uuid": uuid,
            "creator": creator_name,
            "is_private": is_private,
            "is_starter_project": is_starter,
            "doc_count": doc_count,
            "updated_at": updated,
        },
    }

    mentions = find_mentions(project)
    edges = []
    for mentioned_project in mentions:
        edges.append({
            "type": "MENTIONS",
            "from_type": "Artifact",
            "from_name": name,
            "to_type": "Project",
            "to_name": sanitize(mentioned_project),
            "properties": {
                "context": f"Claude project references {sanitize(mentioned_project)}",
            },
        })

    extraction = {
        "artifact": artifact,
        "projects": [],
        "concepts": [],
        "decisions": [],
        "persons": [],
        "edges": edges,
    }
    return extraction, len(edges)


def main():
    print(f"Loading {SOURCE_FILE}...")
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        projects = json.load(f)

    total_projects = len(projects)
    print(f"Found {total_projects} projects")

    os.makedirs(EXTRACTIONS_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    artifacts_created = 0
    total_edges = 0
    errors = 0
    extraction_files = []

    for i, project in enumerate(projects):
        name = sanitize(project.get("name", f"unnamed-{i}"))
        print(f"\n[{i+1}/{total_projects}] Processing: {name}")

        try:
            extraction, edge_count = build_extraction(project)
            total_edges += edge_count

            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:60]
            filename = f"{safe_name}.json"
            filepath = os.path.join(EXTRACTIONS_DIR, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(extraction, f, indent=2, ensure_ascii=False)

            extraction_files.append(filepath)
            artifacts_created += 1
            mentions = [e["to_name"] for e in extraction["edges"]]
            if mentions:
                print(f"  Mentions: {', '.join(mentions)}")
            else:
                print(f"  No known project mentions found")

        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1

    print(f"\n{'='*60}")
    print(f"Running graph_writer.py on {len(extraction_files)} extraction files...")
    print(f"{'='*60}")

    writer_errors = 0
    for filepath in extraction_files:
        print(f"\n--- {os.path.basename(filepath)} ---")
        result = subprocess.run(
            [PYTHON, GRAPH_WRITER, filepath],
            capture_output=True, text=True, encoding="utf-8"
        )
        print(result.stdout)
        if result.stderr:
            print(f"STDERR: {result.stderr}")
        if result.returncode != 0:
            writer_errors += 1
            errors += 1

    dest = os.path.join(PROCESSED_DIR, "projects.json")
    try:
        shutil.move(SOURCE_FILE, dest)
        print(f"\nMoved {SOURCE_FILE} -> {dest}")
    except Exception as e:
        print(f"\nERROR moving file: {e}")
        errors += 1

    print(f"\n{'='*60}")
    print(f"REPORT")
    print(f"{'='*60}")
    print(f"Total projects found:  {total_projects}")
    print(f"Artifacts created:     {artifacts_created}")
    print(f"MENTIONS edges:        {total_edges}")
    print(f"Graph writer errors:   {writer_errors}")
    print(f"Total errors:          {errors}")
    print(f"Extractions dir:       {EXTRACTIONS_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
