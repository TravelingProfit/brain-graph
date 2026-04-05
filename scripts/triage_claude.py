"""
Triage Claude AI conversation JSON files for Second Brain knowledge graph.
Classifies each as DEEP, LIGHT, or SKIP based on signal density.
"""
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import cfg


def load_projects_config():
    config_path = Path(__file__).parent.parent / "projects.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"projects": {}, "concept_keywords": {}, "location_rules": {}, "notebook_mappings": {}, "triage_keywords": {}}


_config = load_projects_config()

SRC_DIR = os.path.join(cfg.BRAIN_INBOX, "claude")
DST_BASE = os.path.join(cfg.BRAIN_INBOX, "classified")

DEEP_DIR = os.path.join(DST_BASE, "deep")
LIGHT_DIR = os.path.join(DST_BASE, "light")
SKIP_DIR = os.path.join(DST_BASE, "skip")

# Build project keywords from all project aliases plus extra triage keywords from config
PROJECT_KEYWORDS = []
for proj_name, proj_info in _config.get("projects", {}).items():
    for alias in proj_info.get("aliases", []):
        if alias not in PROJECT_KEYWORDS:
            PROJECT_KEYWORDS.append(alias)
for extra_kw in _config.get("triage_keywords", {}).get("project_extra", []):
    if extra_kw not in PROJECT_KEYWORDS:
        PROJECT_KEYWORDS.append(extra_kw)

# Patterns that signal DEEP architectural/strategic content
DEEP_TITLE_PATTERNS = [
    "architect", "design", "strategy", "planning", "comparison",
    "infrastructure", "pipeline", "workflow", "framework", "migration",
    "integration", "deployment", "system", "stack", "roadmap",
    "decision", "evaluation", "choose", "choosing", "versus", " vs ",
    "business", "pricing", "revenue", "model", "schema",
    "embedding", "vector", "graph", "ontology", "taxonomy",
    "docker", "kubernetes", "self-host", "homelab",
    "api design", "data model", "entity", "automation",
]

# Patterns that signal SKIP
SKIP_TITLE_PATTERNS = [
    "translate", "translation", "regex", "format", "converter",
    "convert", "test message", "hello", "untitled",
]

# Patterns that signal LIGHT (debugging, how-to, quick fixes)
LIGHT_TITLE_PATTERNS = [
    "fix", "error", "bug", "debug", "how to", "how do",
    "install", "setup guide", "troubleshoot", "syntax",
    "snippet", "example", "sample", "template",
]


def classify(name, msg_count):
    """Return (classification, reason) tuple."""
    title = (name or "").strip().lower()

    if (not title or title in ("", "new chat", "untitled")) and msg_count < 3:
        return "SKIP", "empty/no title + <3 messages"

    if msg_count <= 2:
        has_project = any(kw in title for kw in PROJECT_KEYWORDS)
        has_deep = any(kw in title for kw in DEEP_TITLE_PATTERNS)
        if has_project or has_deep:
            return "LIGHT", f"project/deep keyword but only {msg_count} messages"
        has_skip = any(kw in title for kw in SKIP_TITLE_PATTERNS)
        if has_skip or not title:
            return "SKIP", f"trivial ({msg_count} messages)"
        return "LIGHT", f"short conversation ({msg_count} msgs) but has title"

    for kw in PROJECT_KEYWORDS:
        if kw in title:
            return "DEEP", f"project keyword: '{kw}'"

    for pattern in DEEP_TITLE_PATTERNS:
        if pattern in title:
            if msg_count > 5:
                return "DEEP", f"architectural pattern: '{pattern}' + {msg_count} msgs"
            else:
                return "LIGHT", f"architectural pattern but short ({msg_count} msgs)"

    for pattern in SKIP_TITLE_PATTERNS:
        if pattern in title:
            if msg_count < 6:
                return "SKIP", f"skip pattern: '{pattern}'"
            else:
                return "LIGHT", f"skip pattern but substantial ({msg_count} msgs)"

    if msg_count > 10 and title:
        return "DEEP", f"specific title + {msg_count} messages"

    if msg_count >= 3 and title:
        return "LIGHT", f"{msg_count} messages with title"

    return "LIGHT", "default fallback"


def main():
    for d in (DEEP_DIR, LIGHT_DIR, SKIP_DIR):
        os.makedirs(d, exist_ok=True)

    results = []
    errors = []
    counts = {"DEEP": 0, "LIGHT": 0, "SKIP": 0}

    files = [f for f in os.listdir(SRC_DIR) if f.endswith(".json")]
    print(f"Found {len(files)} JSON files to process.\n")

    for fname in sorted(files):
        fpath = os.path.join(SRC_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)

            name = data.get("name", "") or ""
            messages = data.get("chat_messages", [])
            msg_count = len(messages)

            classification, reason = classify(name, msg_count)
            counts[classification] += 1

            dst_map = {"DEEP": DEEP_DIR, "LIGHT": LIGHT_DIR, "SKIP": SKIP_DIR}
            dst_path = os.path.join(dst_map[classification], fname)
            shutil.move(fpath, dst_path)

            results.append({
                "file": fname,
                "title": name,
                "msg_count": msg_count,
                "classification": classification,
                "reason": reason,
            })

        except Exception as e:
            errors.append((fname, str(e)))

    print(f"{'FILE':<45} {'MSGS':>4}  {'CLASS':<6} {'TITLE'}")
    print("-" * 120)
    for r in results:
        short_title = (r["title"] or "(no title)")[:55]
        print(f"{r['file']:<45} {r['msg_count']:>4}  {r['classification']:<6} {short_title}")

    print(f"\n{'='*60}")
    print(f"TOTAL: {len(results)} files processed")
    print(f"  DEEP:  {counts['DEEP']}")
    print(f"  LIGHT: {counts['LIGHT']}")
    print(f"  SKIP:  {counts['SKIP']}")

    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for fname, err in errors:
            print(f"  {fname}: {err}")

    deep_items = [r for r in results if r["classification"] == "DEEP"]
    if deep_items:
        print(f"\n{'='*60}")
        print("DEEP CONVERSATIONS:")
        for r in sorted(deep_items, key=lambda x: -x["msg_count"]):
            print(f"  [{r['msg_count']:>3} msgs] {r['title'] or '(no title)'}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
