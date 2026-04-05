#!/usr/bin/env python3
"""
Process Grok AI export for the Second Brain knowledge graph.
Loads conversations, filters Thai content, classifies DEEP/LIGHT,
extracts entities, writes to ArcadeDB via graph_writer.py.

Usage: python process_grok.py [<grok_json_path>] [limit]
  If no path given, looks for prod-grok-backend.json in cfg.BRAIN_INBOX/grok/
"""
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
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

# Paths
EXTRACTION_DIR = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "extractions", "grok"))
GRAPH_WRITER = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "graph_writer.py"))
PYTHON = sys.executable
GROK_INBOX = Path(os.path.join(cfg.BRAIN_INBOX, "grok"))
PROCESSED_DIR = Path(os.path.join(cfg.BRAIN_INBOX, "processed", "grok"))

# Thai character detection
THAI_PATTERN = re.compile(r'[\u0e00-\u0e7f]')

# Build project keyword -> canonical name mapping from config
KNOWN_PROJECTS = {}
for proj_name, proj_info in _config.get("projects", {}).items():
    for alias in proj_info.get("aliases", []):
        KNOWN_PROJECTS[alias] = proj_name

# Build concept keyword -> canonical name mapping from config
KNOWN_CONCEPTS = {k: v for k, v in _config.get("concept_keywords", {}).items() if k != "_comment"}

# Decision indicator patterns
DECISION_PATTERNS = [
    r"(?:chose|decided|going with|went with|picked|selected|opting for|opted for)\s+(.{10,80}?)(?:\s+(?:because|since|due to|as|for)\s+(.{10,100}))?[.\n]",
    r"(?:instead of|rather than|over)\s+(.{10,60}?)(?:\s*,\s*|\s+)(?:chose|went with|using|picked)\s+(.{10,60})",
    r"(?:decision|decided):\s*(.{10,120})",
]

# Architecture/planning keywords for DEEP classification
DEEP_KEYWORDS = [
    "architecture", "design pattern", "system design", "infrastructure",
    "deployment", "migration", "roadmap", "strategy", "planning",
    "decision", "trade-off", "tradeoff", "comparison", "evaluation",
    "implementation plan", "tech stack", "database schema", "api design",
    "security model", "authentication", "authorization", "scaling",
    "performance", "optimization", "monitoring", "observability",
    "ci/cd", "pipeline", "workflow", "automation", "integration",
    "data model", "entity relationship", "schema design",
    "cost analysis", "budget", "pricing", "revenue model",
    "business plan", "market analysis", "competitive analysis",
    "legal structure", "corporate structure", "holding",
    "investment", "portfolio", "asset allocation",
]


def strip_apostrophes(s):
    """Remove apostrophes from strings to prevent SQL parser issues."""
    if not isinstance(s, str):
        return s
    s = s.replace("it's", "it is").replace("It's", "It is")
    s = s.replace("that's", "that is").replace("That's", "That is")
    s = s.replace("what's", "what is").replace("What's", "What is")
    s = s.replace("there's", "there is").replace("There's", "There is")
    s = s.replace("here's", "here is").replace("Here's", "Here is")
    s = s.replace("let's", "let us").replace("Let's", "Let us")
    s = s.replace("don't", "do not").replace("Don't", "Do not")
    s = s.replace("doesn't", "does not").replace("Doesn't", "Does not")
    s = s.replace("didn't", "did not").replace("Didn't", "Did not")
    s = s.replace("won't", "will not").replace("Won't", "Will not")
    s = s.replace("can't", "cannot").replace("Can't", "Cannot")
    s = s.replace("isn't", "is not").replace("Isn't", "Is not")
    s = s.replace("'s", "s").replace("'t", "t")
    s = s.replace("'re", " are").replace("'ve", " have")
    s = s.replace("'ll", " will").replace("'d", " would")
    s = s.replace("'", "").replace("\u2019", "").replace("\u2018", "")
    return s


def has_thai(text):
    if not text:
        return False
    return bool(THAI_PATTERN.search(text))


def conversation_has_thai(conv_item):
    conv = conv_item.get("conversation", {})
    title = conv.get("title", "") or ""
    if has_thai(title):
        return True
    for r in conv_item.get("responses", []):
        msg = r.get("response", {}).get("message", "") or ""
        if has_thai(msg):
            return True
    return False


def get_full_text(conv_item):
    texts = []
    for r in conv_item.get("responses", []):
        msg = r.get("response", {}).get("message", "") or ""
        if msg:
            texts.append(msg)
    return "\n\n".join(texts)


def get_timestamp(conv_item):
    return conv_item.get("conversation", {}).get("create_time", "")


def get_msg_count(conv_item):
    return len(conv_item.get("responses", []))


def classify_conversation(conv_item, full_text):
    msg_count = get_msg_count(conv_item)
    conv = conv_item.get("conversation", {})
    title = conv.get("title", "") or ""

    if msg_count <= 10:
        return "LIGHT"

    text_lower = full_text.lower()
    deep_score = sum(1 for kw in DEEP_KEYWORDS if kw in text_lower)

    if title and len(title) > 5 and deep_score >= 3:
        return "DEEP"

    return "LIGHT"


def find_projects(text):
    text_lower = text.lower()
    found = {}
    for pattern, canonical in KNOWN_PROJECTS.items():
        if pattern in text_lower:
            found[canonical] = True
    return list(found.keys())


def find_concepts(text):
    text_lower = text.lower()
    found = Counter()
    for pattern, canonical in KNOWN_CONCEPTS.items():
        if len(pattern) <= 3:
            count = len(re.findall(r'\b' + re.escape(pattern) + r'\b', text_lower))
        else:
            count = text_lower.count(pattern)
        if count > 0:
            found[canonical] += count
    return {name: count for name, count in found.items() if count >= 2}


def find_new_concepts(text):
    caps_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b'
    matches = re.findall(caps_pattern, text)
    counts = Counter(matches)

    skip_phrases = {"The", "This", "That", "These", "Those", "What", "When",
                    "Where", "How", "Which", "Would", "Could", "Should",
                    "Here", "There", "Thank", "Sure", "Great", "Good",
                    "First", "Second", "Third", "Last", "Next", "New",
                    "Each", "Every", "Some", "Any", "All", "Most",
                    "For", "With", "From", "Into", "Over", "Under",
                    "About", "After", "Before", "Between", "During"}
    skip_suffixes = {"Agent", "Writer", "Manager", "Monitor", "Editor",
                     "Designer", "Engineer", "Specialist", "Planner",
                     "Creator", "Builder", "Handler", "Processor",
                     "Analyzer", "Responder", "Qualifier", "Artist",
                     "Tracker", "Reporter", "Controller", "Coordinator"}

    new_concepts = []
    for term, count in counts.items():
        if count < 5:
            continue
        if term.lower() in KNOWN_CONCEPTS or term in KNOWN_CONCEPTS.values():
            continue
        words = term.split()
        if words[0] in skip_phrases or words[-1] in skip_suffixes:
            continue
        if len(term) < 8:
            continue
        new_concepts.append({"name": strip_apostrophes(term), "count": count})

    new_concepts.sort(key=lambda x: x["count"], reverse=True)
    return new_concepts[:5]


def find_decisions(text):
    decisions = []
    for pattern in DECISION_PATTERNS:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for m in matches:
            groups = m.groups()
            what = groups[0].strip() if groups[0] else ""
            reasoning = groups[1].strip() if len(groups) > 1 and groups[1] else ""
            if 10 < len(what) < 150:
                decisions.append({
                    "what": strip_apostrophes(what),
                    "reasoning": strip_apostrophes(reasoning)
                })

    seen = set()
    unique = []
    for d in decisions:
        key = d["what"][:40]
        if key not in seen:
            seen.add(key)
            unique.append(d)
        if len(unique) >= 3:
            break
    return unique


def make_safe_filename(title, conv_id):
    if not title or len(title.strip()) < 3:
        return conv_id
    safe = re.sub(r'[^\w\s-]', '', title.lower())
    safe = re.sub(r'\s+', '-', safe.strip())
    safe = safe[:60]
    return safe or conv_id


def build_extraction(conv_item, classification, full_text):
    conv = conv_item.get("conversation", {})
    conv_id = conv.get("id", "unknown")
    title = strip_apostrophes(conv.get("title", "") or "Untitled Grok Conversation")
    timestamp = get_timestamp(conv_item)
    msg_count = get_msg_count(conv_item)

    projects = find_projects(full_text)
    concept_counts = find_concepts(full_text)

    top_concepts = sorted(concept_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    concept_names = [c[0] for c in top_concepts]
    parts = [f"Grok conversation: {title}."]
    if projects:
        parts.append(f"Related to: {', '.join(projects)}.")
    if concept_names:
        parts.append(f"Key topics: {', '.join(concept_names)}.")
    parts.append(f"{msg_count} messages, classified {classification}.")
    summary = " ".join(parts)[:400]

    extraction = {
        "artifact": {
            "name": title,
            "source_type": "grok",
            "source_path": f"brain-inbox/grok/{conv_id}",
            "content_hash": f"grok-{conv_id}",
            "summary": summary,
            "source_timestamp": timestamp,
            "metadata": {"conversation_id": conv_id, "message_count": msg_count, "classification": classification}
        },
        "concepts": [],
        "decisions": [],
        "projects": [],
        "persons": [],
        "edges": []
    }

    for concept_name, count in concept_counts.items():
        extraction["edges"].append({
            "type": "MENTIONS",
            "from_type": "Artifact",
            "from_name": title,
            "to_type": "Concept",
            "to_name": concept_name,
            "properties": {"weight": min(count / 10.0, 1.0)}
        })

    for proj in projects:
        extraction["edges"].append({
            "type": "MENTIONS",
            "from_type": "Artifact",
            "from_name": title,
            "to_type": "Project",
            "to_name": proj,
            "properties": {"context": "referenced in Grok conversation"}
        })

    if classification == "DEEP":
        new_concepts_raw = find_new_concepts(full_text)
        decisions = find_decisions(full_text)

        for nc in new_concepts_raw:
            extraction["concepts"].append({
                "name": nc["name"],
                "description": f"Concept mentioned {nc['count']} times in Grok conversation",
                "aliases": [],
                "source": "grok"
            })
            extraction["edges"].append({
                "type": "MENTIONS",
                "from_type": "Artifact",
                "from_name": title,
                "to_type": "Concept",
                "to_name": nc["name"],
                "properties": {"weight": min(nc["count"] / 10.0, 1.0)}
            })

        for i, d in enumerate(decisions):
            dec_name = f"{title} - Decision {i+1}"
            if len(dec_name) > 80:
                dec_name = dec_name[:77] + "..."
            extraction["decisions"].append({
                "name": dec_name,
                "what": d["what"],
                "alternatives": [],
                "reasoning": d["reasoning"],
                "confidence": "medium",
                "still_valid": True
            })
            extraction["edges"].append({
                "type": "MENTIONS",
                "from_type": "Artifact",
                "from_name": title,
                "to_type": "Decision",
                "to_name": dec_name,
                "properties": {"context": "decision made in Grok conversation"}
            })

    return extraction


def find_grok_json():
    """Find the Grok export JSON file in the inbox."""
    # Walk the grok inbox looking for prod-grok-backend.json
    for root, dirs, files in os.walk(str(GROK_INBOX)):
        for f in files:
            if f == "prod-grok-backend.json":
                return os.path.join(root, f)
    return None


def main():
    EXTRACTION_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # Determine source file
    grok_json = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].isdigit() else find_grok_json()
    if not grok_json or not os.path.exists(grok_json):
        print(f"ERROR: Grok export JSON not found. Looked in {GROK_INBOX}")
        print("Usage: python process_grok.py [<path_to_grok_json>] [limit]")
        sys.exit(1)

    print(f"Loading {grok_json} ...")
    with open(grok_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    conversations = data.get("conversations", [])
    total = len(conversations)
    print(f"Total conversations in export: {total}")
    print("=" * 80)

    skipped_thai = 0
    skipped_trivial = 0
    processed_deep = 0
    processed_light = 0
    total_artifacts = 0
    total_concepts = 0
    total_edges = 0
    total_errors = 0

    # Parse limit from args
    limit = total
    for arg in sys.argv[1:]:
        if arg.isdigit():
            limit = int(arg)
            break

    for i, conv_item in enumerate(conversations[:limit]):
        conv = conv_item.get("conversation", {})
        conv_id = conv.get("id", "unknown")
        title = conv.get("title", "") or ""
        msg_count = get_msg_count(conv_item)

        if conversation_has_thai(conv_item):
            skipped_thai += 1
            continue

        if msg_count < 3:
            skipped_trivial += 1
            continue

        full_text = get_full_text(conv_item)
        classification = classify_conversation(conv_item, full_text)

        try:
            extraction = build_extraction(conv_item, classification, full_text)

            safe_name = make_safe_filename(title, conv_id)
            ext_path = EXTRACTION_DIR / f"{safe_name}.json"

            counter = 1
            while ext_path.exists():
                ext_path = EXTRACTION_DIR / f"{safe_name}-{counter}.json"
                counter += 1

            with open(ext_path, "w", encoding="utf-8") as f:
                json.dump(extraction, f, indent=2, ensure_ascii=False)

            result = subprocess.run(
                [PYTHON, str(GRAPH_WRITER), str(ext_path)],
                capture_output=True, text=True, timeout=30
            )

            if result.returncode != 0:
                print(f"  [{i+1}] GRAPH WRITER ERROR for {title[:50]}: {result.stderr[:200]}")
                total_errors += 1
            else:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        print(f"  {line.strip()}")

            if classification == "DEEP":
                processed_deep += 1
            else:
                processed_light += 1

            total_artifacts += 1
            total_concepts += len(extraction.get("concepts", []))
            total_edges += len(extraction.get("edges", []))

            status = "DEEP" if classification == "DEEP" else "LIGHT"
            print(f"  [{i+1}/{total}] {status}: {title[:60]} ({msg_count} msgs, {len(extraction['edges'])} edges)")

        except Exception as e:
            print(f"  [{i+1}] ERROR processing {conv_id}: {e}")
            total_errors += 1

    print("\n" + "=" * 80)
    print("Moving grok inbox to processed...")
    try:
        if GROK_INBOX.exists():
            if PROCESSED_DIR.exists():
                shutil.rmtree(PROCESSED_DIR)
            shutil.copytree(str(GROK_INBOX), str(PROCESSED_DIR))
            shutil.rmtree(str(GROK_INBOX))
            print(f"  Moved {GROK_INBOX} -> {PROCESSED_DIR}")
    except Exception as e:
        print(f"  ERROR moving files: {e}")
        total_errors += 1

    print("\n" + "=" * 80)
    print("GROK EXPORT PROCESSING - FINAL REPORT")
    print("=" * 80)
    print(f"Total conversations in export: {total}")
    print(f"Skipped (Thai content):        {skipped_thai}")
    print(f"Skipped (trivial <3 msgs):     {skipped_trivial}")
    print(f"Processed DEEP:                {processed_deep}")
    print(f"Processed LIGHT:               {processed_light}")
    print(f"---")
    print(f"Artifacts created:             {total_artifacts}")
    print(f"New concepts created:          {total_concepts}")
    print(f"Edges created:                 {total_edges}")
    print(f"Errors:                        {total_errors}")
    print("=" * 80)


if __name__ == "__main__":
    main()
