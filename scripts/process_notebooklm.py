#!/usr/bin/env python3
"""
Process NotebookLM notebook exports into Second Brain knowledge graph.
Creates Artifact nodes, extracts Concepts from .md artifacts,
and creates MENTIONS edges to known projects.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import hashlib
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
INBOX_DIR = os.path.join(cfg.BRAIN_INBOX, "notebooklm")
EXTRACTIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "extractions", "notebooklm")
PROCESSED_DIR = os.path.join(cfg.BRAIN_INBOX, "processed", "notebooklm")

# Load notebook folder name -> project name mapping from config
PROJECT_MAP = {k: v for k, v in _config.get("notebook_mappings", {}).items() if k != "_comment"}

stats = {
    "notebooks_processed": 0,
    "artifacts_created": 0,
    "concepts_created": 0,
    "edges_created": 0,
    "errors": [],
}


def strip_apostrophes(s):
    """Remove all apostrophes from a string."""
    if s is None:
        return ""
    return str(s).replace("'", "").replace("\u2019", "").replace("\u2018", "")


def make_slug(name):
    """Create a URL-safe slug from a name."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:80]


def clean_notebook_name(folder_name):
    """Clean up notebook folder name for display."""
    name = folder_name.strip()
    name = re.sub(r"_$", "", name)
    fixups = {
        "AI Agent Protocols_ Standards for Communication an":
            "AI Agent Protocols - Standards for Communication",
        "AI Video Production Architecture_ Scalable Factory":
            "AI Video Production Architecture - Scalable Factory",
        "Building a Second Brain with AI_ Engineering for E":
            "Building a Second Brain with AI - Engineering for Emergence",
        "Governance-Native Agent Runtime Technology Evaluat":
            "Governance-Native Agent Runtime Technology Evaluation",
        "Grand Slam Offers_ The $100M Entrepreneurial Bluep":
            "Grand Slam Offers - The 100M Entrepreneurial Blueprint",
        "OpenClaw and OpenCode_ Implementation and Troubles":
            "OpenClaw and OpenCode - Implementation and Troubleshooting",
    }
    name = fixups.get(folder_name, name)
    name = name.replace("_", " ").replace("  ", " ")
    name = strip_apostrophes(name)
    return name


def find_metadata_json(folder_path):
    """Find the top-level metadata .json file in a notebook folder."""
    for f in os.listdir(folder_path):
        if f.endswith(".json") and os.path.isfile(os.path.join(folder_path, f)):
            return os.path.join(folder_path, f)
    return None


def count_files(folder_path, subfolder, extensions):
    """Count files with given extensions in a subfolder."""
    sub = os.path.join(folder_path, subfolder)
    if not os.path.isdir(sub):
        return 0
    count = 0
    for f in os.listdir(sub):
        if any(f.lower().endswith(ext) for ext in extensions):
            count += 1
    return count


def read_md_artifacts(folder_path):
    """Read all .md files from the Artifacts subfolder."""
    art_dir = os.path.join(folder_path, "Artifacts")
    if not os.path.isdir(art_dir):
        return []
    results = []
    for f in os.listdir(art_dir):
        if f.lower().endswith(".md"):
            fpath = os.path.join(art_dir, f)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                results.append({"filename": f, "content": content})
            except Exception as e:
                stats["errors"].append(f"Error reading {fpath}: {e}")
    return results


def read_chat_summary(folder_path):
    """Read first chat HTML file and extract a brief text summary."""
    chat_dir = os.path.join(folder_path, "Chat History")
    if not os.path.isdir(chat_dir):
        return ""
    html_files = [f for f in os.listdir(chat_dir) if f.lower().endswith(".html")]
    if not html_files:
        return ""
    fpath = os.path.join(chat_dir, html_files[0])
    try:
        with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:500]
    except Exception:
        return ""


def extract_concepts_from_md(md_content, notebook_name):
    """Extract concepts from markdown content using heading analysis."""
    concepts = []
    headings = re.findall(r"^#{2,5}\s+(.+)$", md_content, re.MULTILINE)

    for heading in headings:
        name = heading.strip().rstrip("#").strip()
        name = re.sub(r"\*\*(.+?)\*\*", r"\1", name)
        name = re.sub(r"\*(.+?)\*", r"\1", name)
        name = strip_apostrophes(name)
        name = name.strip(": ")

        if len(name) < 5 or len(name) > 120:
            continue
        if re.match(r"^\d+\.?\s*$", name):
            continue

        pattern = re.escape(heading) + r"\s*\n([\s\S]*?)(?=\n#{2,5}\s|\Z)"
        match = re.search(pattern, md_content)
        desc = ""
        if match:
            desc = match.group(1).strip()
            desc = re.sub(r"\*\*(.+?)\*\*", r"\1", desc)
            desc = re.sub(r"\*(.+?)\*", r"\1", desc)
            desc = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", desc)
            desc = re.sub(r"<[^>]+>", "", desc)
            desc = re.sub(r"\s+", " ", desc).strip()
            desc = strip_apostrophes(desc)
            if len(desc) > 300:
                desc = desc[:297] + "..."

        concepts.append({
            "name": name,
            "description": desc,
            "aliases": [],
            "source": "notebooklm",
        })

    return concepts


def extract_key_terms(md_content):
    """Extract bold terms as additional lightweight concepts."""
    terms = re.findall(r"\*\*([A-Z][^*]{3,60})\*\*", md_content)
    seen = set()
    results = []
    for term in terms:
        clean = strip_apostrophes(term.strip(": "))
        key = clean.lower()
        if key in seen or len(clean) < 5:
            continue
        seen.add(key)
        results.append({
            "name": clean,
            "description": "",
            "aliases": [],
            "source": "notebooklm",
        })
    return results


def build_extraction(folder_name, folder_path):
    """Build a complete extraction JSON for one notebook."""
    clean_name = clean_notebook_name(folder_name)
    slug = make_slug(folder_name)

    meta_path = find_metadata_json(folder_path)
    meta = {}
    if meta_path:
        try:
            with open(meta_path, "r", encoding="utf-8", errors="replace") as f:
                meta = json.load(f)
        except Exception as e:
            stats["errors"].append(f"Error reading metadata {meta_path}: {e}")

    title = strip_apostrophes(meta.get("title", clean_name))
    created = meta.get("metadata", {}).get("createTime", "")
    last_viewed = meta.get("metadata", {}).get("lastViewed", "")

    source_count = count_files(folder_path, "Sources", [".html"])
    chat_count = count_files(folder_path, "Chat History", [".html"])
    artifact_md_count = count_files(folder_path, "Artifacts", [".md"])
    artifact_json_count = count_files(folder_path, "Artifacts", [".json"])
    artifact_count = artifact_md_count + artifact_json_count

    md_artifacts = read_md_artifacts(folder_path)

    summary_parts = [f"NotebookLM notebook: {title}."]
    if source_count:
        summary_parts.append(f"{source_count} sources.")
    if chat_count:
        summary_parts.append(f"{chat_count} chat sessions.")
    if artifact_md_count:
        summary_parts.append(f"{artifact_md_count} generated artifacts.")

    for art in md_artifacts:
        preview = art["content"][:200].replace("\n", " ").strip()
        preview = strip_apostrophes(preview)
        if preview:
            summary_parts.append(f"Artifact [{art['filename']}]: {preview}")

    if not md_artifacts:
        chat_text = read_chat_summary(folder_path)
        if chat_text:
            chat_text = strip_apostrophes(chat_text[:200])
            summary_parts.append(f"Chat context: {chat_text}")

    summary = " ".join(summary_parts)
    if len(summary) > 1000:
        summary = summary[:997] + "..."
    summary = strip_apostrophes(summary)

    artifact = {
        "name": strip_apostrophes(clean_name),
        "source_type": "notebooklm",
        "source_path": folder_path.replace("\\", "/"),
        "content_hash": f"notebooklm-{slug}",
        "summary": summary,
        "source_timestamp": created[:10] if created else "",
        "metadata": {
            "source_count": source_count,
            "chat_count": chat_count,
            "artifact_count": artifact_count,
            "last_viewed": last_viewed,
            "notebook_title": strip_apostrophes(title),
        },
    }

    concepts = []
    seen_concepts = set()
    for art in md_artifacts:
        if len(art["content"]) > 500:
            heading_concepts = extract_concepts_from_md(art["content"], clean_name)
            for c in heading_concepts:
                key = c["name"].lower()
                if key not in seen_concepts:
                    seen_concepts.add(key)
                    concepts.append(c)

            key_terms = extract_key_terms(art["content"])
            for c in key_terms:
                key = c["name"].lower()
                if key not in seen_concepts:
                    seen_concepts.add(key)
                    concepts.append(c)

    edges = []

    for c in concepts:
        edges.append({
            "type": "MENTIONS",
            "from_type": "Artifact",
            "from_name": strip_apostrophes(clean_name),
            "to_type": "Concept",
            "to_name": c["name"],
            "properties": {"context": "extracted from notebooklm artifact"},
        })

    for pattern, project in PROJECT_MAP.items():
        if pattern.lower() in folder_name.lower():
            edges.append({
                "type": "MENTIONS",
                "from_type": "Artifact",
                "from_name": strip_apostrophes(clean_name),
                "to_type": "Project",
                "to_name": strip_apostrophes(project),
                "properties": {"context": f"NotebookLM notebook related to {strip_apostrophes(project)}"},
            })
            break

    extraction = {
        "artifact": artifact,
        "concepts": concepts,
        "projects": [],
        "persons": [],
        "decisions": [],
        "edges": edges,
    }

    return extraction


def process_all():
    """Process all notebook folders."""
    os.makedirs(EXTRACTIONS_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    folders = sorted([
        d for d in os.listdir(INBOX_DIR)
        if os.path.isdir(os.path.join(INBOX_DIR, d))
    ])

    print(f"Found {len(folders)} notebook folders")
    print("=" * 60)

    for folder_name in folders:
        folder_path = os.path.join(INBOX_DIR, folder_name)
        print(f"\nProcessing: {folder_name}")

        try:
            extraction = build_extraction(folder_name, folder_path)

            slug = make_slug(folder_name)
            out_path = os.path.join(EXTRACTIONS_DIR, f"{slug}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(extraction, f, indent=2, ensure_ascii=False)

            print(f"  Wrote: {out_path}")
            print(f"  Concepts: {len(extraction['concepts'])}, Edges: {len(extraction['edges'])}")

            result = subprocess.run(
                [PYTHON, GRAPH_WRITER, out_path],
                capture_output=True, text=True, timeout=30,
            )
            print(result.stdout.strip())
            if result.stderr.strip():
                print(f"  STDERR: {result.stderr.strip()}")
            if result.returncode != 0:
                stats["errors"].append(f"graph_writer failed for {folder_name}: rc={result.returncode}")

            stats["notebooks_processed"] += 1
            stats["artifacts_created"] += 1
            stats["concepts_created"] += len(extraction["concepts"])
            stats["edges_created"] += len(extraction["edges"])

        except Exception as e:
            stats["errors"].append(f"Error processing {folder_name}: {e}")
            print(f"  ERROR: {e}")

    print("\n" + "=" * 60)
    print("Moving processed files...")
    try:
        for folder_name in folders:
            src = os.path.join(INBOX_DIR, folder_name)
            dst = os.path.join(PROCESSED_DIR, folder_name)
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.move(src, dst)
            print(f"  Moved: {folder_name}")
    except Exception as e:
        stats["errors"].append(f"Error moving files: {e}")
        print(f"  ERROR moving: {e}")

    print("\n" + "=" * 60)
    print("FINAL REPORT")
    print("=" * 60)
    print(f"Notebooks processed: {stats['notebooks_processed']}")
    print(f"Artifacts created:   {stats['artifacts_created']}")
    print(f"Concepts created:    {stats['concepts_created']}")
    print(f"Edges created:       {stats['edges_created']}")
    if stats["errors"]:
        print(f"Errors ({len(stats['errors'])}):")
        for e in stats["errors"]:
            print(f"  - {e}")
    else:
        print("Errors: 0")


if __name__ == "__main__":
    process_all()
