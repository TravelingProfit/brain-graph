#!/usr/bin/env python3
"""
Batch extract entities from DEEP-classified Claude conversations and write to ArcadeDB.
Processes all .json files in classified/deep/, creates extraction JSONs,
calls graph_writer.py, and moves processed files.
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
DEEP_DIR = Path(os.path.join(cfg.BRAIN_INBOX, "classified", "deep"))
EXTRACTION_DIR = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "extractions", "claude"))
PROCESSED_DIR = Path(os.path.join(cfg.BRAIN_INBOX, "processed"))
GRAPH_WRITER = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "graph_writer.py"))
PYTHON = sys.executable

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
    s = s.replace("wouldn't", "would not").replace("Wouldn't", "Would not")
    s = s.replace("couldn't", "could not").replace("Couldn't", "Could not")
    s = s.replace("shouldn't", "should not").replace("Shouldn't", "Should not")
    s = s.replace("can't", "cannot").replace("Can't", "Cannot")
    s = s.replace("isn't", "is not").replace("Isn't", "Is not")
    s = s.replace("aren't", "are not").replace("Aren't", "Are not")
    s = s.replace("wasn't", "was not").replace("Wasn't", "Was not")
    s = s.replace("weren't", "were not").replace("Weren't", "Were not")
    s = s.replace("haven't", "have not").replace("Haven't", "Have not")
    s = s.replace("hasn't", "has not").replace("Hasn't", "Has not")
    s = s.replace("hadn't", "had not").replace("Hadn't", "Had not")
    s = s.replace("I'm", "I am").replace("I've", "I have")
    s = s.replace("I'll", "I will").replace("I'd", "I would")
    s = s.replace("you're", "you are").replace("You're", "You are")
    s = s.replace("you've", "you have").replace("You've", "You have")
    s = s.replace("you'll", "you will").replace("You'll", "You will")
    s = s.replace("you'd", "you would").replace("You'd", "You would")
    s = s.replace("we're", "we are").replace("We're", "We are")
    s = s.replace("we've", "we have").replace("We've", "We have")
    s = s.replace("we'll", "we will").replace("We'll", "We will")
    s = s.replace("we'd", "we would").replace("We'd", "We would")
    s = s.replace("they're", "they are").replace("They're", "They are")
    s = s.replace("they've", "they have").replace("They've", "They have")
    s = s.replace("they'll", "they will").replace("They'll", "They will")
    s = s.replace("they'd", "they would").replace("They'd", "They would")
    s = s.replace("'s", "s").replace("'t", "t")
    s = s.replace("'re", " are").replace("'ve", " have")
    s = s.replace("'ll", " will").replace("'d", " would")
    s = s.replace("'", "").replace("\u2019", "").replace("\u2018", "")
    return s


def extract_full_text(conversation):
    """Extract all message text from a conversation."""
    messages = conversation.get("chat_messages", [])
    texts = []
    for msg in messages:
        text = msg.get("text", "")
        if text:
            texts.append(text)
    return "\n\n".join(texts)


def find_projects(text):
    """Find known projects mentioned in text."""
    text_lower = text.lower()
    found = {}
    for pattern, canonical in KNOWN_PROJECTS.items():
        if pattern in text_lower:
            found[canonical] = True
    return list(found.keys())


def find_concepts(text):
    """Find known concepts mentioned in text, return those with 2+ mentions."""
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
    """Find potential NEW concepts from capitalized multi-word terms appearing 5+ times."""
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
        if words[0] in skip_phrases:
            continue
        if words[-1] in skip_suffixes:
            continue
        if len(term) < 8:
            continue
        new_concepts.append({"name": strip_apostrophes(term), "count": count})

    new_concepts.sort(key=lambda x: x["count"], reverse=True)
    return new_concepts[:5]


def find_decisions(text):
    """Find decision patterns in text."""
    decisions = []
    for pattern in DECISION_PATTERNS:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for m in matches:
            groups = m.groups()
            what = groups[0].strip() if groups[0] else ""
            reasoning = groups[1].strip() if len(groups) > 1 and groups[1] else ""
            if len(what) > 10 and len(what) < 150:
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


def generate_summary(conversation, text, projects, concepts):
    """Generate a brief summary from the conversation name and content."""
    name = conversation.get("name", "Untitled")
    summary_from_conv = conversation.get("summary", "")

    if summary_from_conv and len(summary_from_conv) > 20:
        return strip_apostrophes(summary_from_conv[:300])

    top_concepts = sorted(concepts.items(), key=lambda x: x[1], reverse=True)[:5]
    concept_names = [c[0] for c in top_concepts]

    parts = [f"Conversation about {strip_apostrophes(name)}."]
    if projects:
        parts.append(f"Related to: {', '.join(projects)}.")
    if concept_names:
        parts.append(f"Key topics: {', '.join(concept_names)}.")

    return " ".join(parts)[:400]


def process_conversation(filepath):
    """Process a single conversation file and return extraction data."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    uuid = data.get("uuid", "")
    name = strip_apostrophes(data.get("name", "Untitled"))
    created_at = data.get("created_at", "")
    messages = data.get("chat_messages", [])
    msg_count = len(messages)

    full_text = extract_full_text(data)

    projects = find_projects(full_text)
    concept_counts = find_concepts(full_text)
    new_concepts_raw = find_new_concepts(full_text)
    decisions = find_decisions(full_text)

    summary = generate_summary(data, full_text, projects, concept_counts)

    extraction = {
        "artifact": {
            "name": name,
            "source_type": "claude",
            "source_path": f"brain-inbox/claude/{uuid}.json",
            "content_hash": f"claude-{uuid}",
            "summary": summary,
            "source_timestamp": created_at,
            "metadata": {"uuid": uuid, "message_count": msg_count}
        },
        "concepts": [],
        "decisions": [],
        "projects": [],
        "persons": [],
        "edges": []
    }

    for nc in new_concepts_raw:
        extraction["concepts"].append({
            "name": nc["name"],
            "description": f"Concept mentioned {nc['count']} times in Claude conversation",
            "aliases": [],
            "source": "claude"
        })

    for i, d in enumerate(decisions):
        dec_name = f"{name} - Decision {i+1}"
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

    for concept_name, count in concept_counts.items():
        extraction["edges"].append({
            "type": "MENTIONS",
            "from_type": "Artifact",
            "from_name": name,
            "to_type": "Concept",
            "to_name": concept_name,
            "properties": {"weight": min(count / 10.0, 1.0)}
        })

    for nc in new_concepts_raw:
        extraction["edges"].append({
            "type": "MENTIONS",
            "from_type": "Artifact",
            "from_name": name,
            "to_type": "Concept",
            "to_name": nc["name"],
            "properties": {"weight": min(nc["count"] / 10.0, 1.0)}
        })

    for proj in projects:
        extraction["edges"].append({
            "type": "MENTIONS",
            "from_type": "Artifact",
            "from_name": name,
            "to_type": "Project",
            "to_name": proj,
            "properties": {"context": "referenced in conversation"}
        })

    for i, d in enumerate(decisions):
        dec_name = f"{name} - Decision {i+1}"
        if len(dec_name) > 80:
            dec_name = dec_name[:77] + "..."
        extraction["edges"].append({
            "type": "MENTIONS",
            "from_type": "Artifact",
            "from_name": name,
            "to_type": "Decision",
            "to_name": dec_name,
            "properties": {"context": "decision made in conversation"}
        })

    return extraction, {
        "concepts_known": len(concept_counts),
        "concepts_new": len(new_concepts_raw),
        "decisions": len(decisions),
        "projects": len(projects),
        "edges": len(extraction["edges"]),
    }


def main():
    EXTRACTION_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    files = sorted(DEEP_DIR.glob("*.json"))
    print(f"Found {len(files)} conversation files to process")
    print("=" * 80)

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(files)
    files = files[:limit]

    total_processed = 0
    total_errors = 0
    total_concepts_known = 0
    total_concepts_new = 0
    total_decisions = 0
    total_projects = 0
    total_edges = 0

    for i, filepath in enumerate(files):
        fname = filepath.name
        print(f"\n[{i+1}/{len(files)}] {fname}")

        try:
            extraction, stats = process_conversation(filepath)

            ext_path = EXTRACTION_DIR / fname
            with open(ext_path, "w", encoding="utf-8") as f:
                json.dump(extraction, f, indent=2, ensure_ascii=False)

            result = subprocess.run(
                [PYTHON, str(GRAPH_WRITER), str(ext_path)],
                capture_output=True, text=True, timeout=30
            )

            if result.returncode != 0:
                print(f"  GRAPH WRITER ERROR: {result.stderr[:200]}")
                total_errors += 1
            else:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        print(f"  {line.strip()}")

                dest = PROCESSED_DIR / fname
                shutil.move(str(filepath), str(dest))

                total_processed += 1

            total_concepts_known += stats["concepts_known"]
            total_concepts_new += stats["concepts_new"]
            total_decisions += stats["decisions"]
            total_projects += stats["projects"]
            total_edges += stats["edges"]

            print(f"  Stats: {stats['concepts_known']} known concepts, {stats['concepts_new']} new concepts, "
                  f"{stats['decisions']} decisions, {stats['projects']} projects, {stats['edges']} edges")

        except Exception as e:
            print(f"  ERROR: {e}")
            total_errors += 1

    print("\n" + "=" * 80)
    print("FINAL REPORT")
    print("=" * 80)
    print(f"Files processed successfully: {total_processed}")
    print(f"Errors: {total_errors}")
    print(f"Known concept mentions: {total_concepts_known}")
    print(f"New concepts created: {total_concepts_new}")
    print(f"Decisions extracted: {total_decisions}")
    print(f"Project references: {total_projects}")
    print(f"Total edges created: {total_edges}")


if __name__ == "__main__":
    main()
