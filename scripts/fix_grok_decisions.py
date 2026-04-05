"""
Fix thin Decision nodes in ArcadeDB by re-extracting reasoning from Grok conversations.

Many Decision nodes have empty or truncated reasoning and what fields due to
regex-based extraction. This script:
1. Queries all thin decisions from ArcadeDB
2. Attempts to match each to a Grok conversation
3. Re-reads conversation content and extracts proper what/reasoning
4. Updates ArcadeDB with enriched content using @rid for safe updates
"""
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import cfg

from difflib import SequenceMatcher


# ---- ArcadeDB helpers (REST API) ----

ARCADEDB_REST = f"http://{cfg.ARCADEDB_HOST}:{cfg.ARCADEDB_PORT}/api/v1/command/{cfg.ARCADEDB_DATABASE}"


def db_run(sql):
    """Execute SQL via ArcadeDB REST API. Returns result list."""
    import urllib.request
    payload = json.dumps({"language": "sql", "command": sql}).encode()
    req = urllib.request.Request(ARCADEDB_REST, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Basic {cfg.ARCADEDB_AUTH}"
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["result"]


def db_update_by_rid(rid, what_val, reasoning_val):
    """Update a Decision record by @rid. Returns True on success."""
    safe_what = sanitize(what_val)
    safe_reasoning = sanitize(reasoning_val)
    sql = f"UPDATE {rid} SET what = '{safe_what}', reasoning = '{safe_reasoning}'"
    result = db_run(sql)
    count = result[0].get("count", 0) if result else 0
    if count != 1:
        print(f"    WARNING: UPDATE {rid} affected {count} records (expected 1)")
        return False
    return True


def sanitize(text):
    """Strip apostrophes and backslashes for SQL string safety."""
    if text is None:
        return ""
    return text.replace("'", "").replace("\\", "")


# ---- Grok conversation helpers ----

def find_grok_json():
    """Find the Grok export JSON in processed or inbox directories."""
    search_dirs = [
        os.path.join(cfg.BRAIN_INBOX, "processed", "grok"),
        os.path.join(cfg.BRAIN_INBOX, "grok"),
    ]
    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for root, dirs, files in os.walk(search_dir):
            for f in files:
                if f == "prod-grok-backend.json":
                    return os.path.join(root, f)
    return None


def load_grok_data(grok_json):
    """Load all conversations from the Grok export JSON."""
    print(f"Loading Grok export from {grok_json} ...")
    with open(grok_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    convos = data.get("conversations", [])
    print(f"  Loaded {len(convos)} conversations")
    return convos


def extract_topic(decision_name):
    """Extract the topic portion from 'Topic - Decision N'."""
    m = re.match(r"^(.+?)\s*-\s*Decision\s+\d+$", decision_name, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return decision_name.strip()


def extract_decision_number(decision_name):
    """Extract the decision number from 'Topic - Decision N'."""
    m = re.search(r"Decision\s+(\d+)", decision_name, re.IGNORECASE)
    return int(m.group(1)) if m else 1


def build_conversation_index(convos):
    """Build a searchable index of conversations with title and message content."""
    index = []
    for conv in convos:
        title = conv["conversation"].get("title", "")
        messages = []
        senders = []
        for r in conv["responses"]:
            messages.append(r["response"].get("message", ""))
            senders.append(r["response"].get("sender", "").lower())
        index.append({
            "title": title,
            "title_lower": title.lower(),
            "messages": messages,
            "senders": senders,
        })
    return index


def find_matching_conversation(topic, conv_index):
    """Find the best matching conversation for a decision topic."""
    topic_lower = topic.lower()
    topic_words = [w for w in topic_lower.split() if len(w) > 2]

    if not topic_words:
        return None, 0

    best_entry = None
    best_score = 0

    for entry in conv_index:
        title_lower = entry["title_lower"]

        ratio = SequenceMatcher(None, topic_lower, title_lower).ratio()
        if ratio > 0.8:
            return entry, ratio

        if topic_lower in title_lower or title_lower in topic_lower:
            return entry, 0.95

        matched = sum(1 for w in topic_words if w in title_lower)
        score = matched / len(topic_words)

        if score > best_score:
            best_score = score
            best_entry = entry

    if best_score >= 0.8:
        return best_entry, best_score

    return None, 0


def extract_decision_from_conversation(conv_entry, decision_number):
    """Extract decision content from conversation messages."""
    messages = conv_entry["messages"]
    senders = conv_entry["senders"]

    if not messages:
        return None, None

    human_msgs = [(i, m) for i, (m, s) in enumerate(zip(messages, senders)) if s == "human"]
    assistant_msgs = [(i, m) for i, (m, s) in enumerate(zip(messages, senders)) if s in ("assistant",)]

    decision_patterns = [
        r"(?:lets?|let us)\s+(?:decide|go with|choose|do|use|pick|stick|plan)",
        r"(?:I(?:ll| will| want to)|we(?:ll| will| should))\s+(?:go|choose|use|pick|decide|opt)",
        r"(?:decided?|choosing|picked|selected|going with)",
        r"(?:okay so lets? decide|the (?:decision|plan|choice) is)",
    ]

    decision_human_msgs = []
    for idx, msg in human_msgs:
        for pat in decision_patterns:
            if re.search(pat, msg.lower()):
                decision_human_msgs.append((idx, msg))
                break

    what = None
    if decision_human_msgs:
        pick = min(decision_number - 1, len(decision_human_msgs) - 1)
        raw = decision_human_msgs[pick][1].strip()
        sentences = re.split(r"(?<=[.!?])\s+", raw)
        what = " ".join(sentences[:3])[:400]
    elif human_msgs:
        for _, msg in reversed(human_msgs):
            if len(msg.strip()) > 30:
                sentences = re.split(r"(?<=[.!?])\s+", msg.strip())
                what = " ".join(sentences[:3])[:400]
                break

    reasoning = None
    summary_patterns = [
        r"###?\s*(?:Summary|Recommendation|Key (?:Points|Takeaways)|Conclusion|Overview|Direct Answer|Assessment)(.*?)(?=\n###|\Z)",
        r"\*\*(?:Summary|Recommendation|Key (?:Points|Takeaways)|Conclusion|Overview)\*\*(.*?)(?=\n\*\*|\Z)",
    ]

    for _, msg in reversed(assistant_msgs):
        if len(msg.strip()) < 50:
            continue
        for pat in summary_patterns:
            m = re.search(pat, msg, re.IGNORECASE | re.DOTALL)
            if m:
                section = m.group(1).strip()
                section = re.sub(r"\n\s*[-*]\s+", "; ", section)
                section = re.sub(r"\s+", " ", section)
                if len(section) > 30:
                    reasoning = section[:500]
                    break
        if reasoning:
            break

    if not reasoning:
        for _, msg in reversed(assistant_msgs):
            if len(msg.strip()) < 100:
                continue
            paragraphs = [p.strip() for p in msg.split("\n\n") if len(p.strip()) > 40]
            if paragraphs:
                reasoning = re.sub(r"\s+", " ", paragraphs[0])[:500]
            break

    return what, reasoning


# ---- Main ----

def main():
    print("=" * 70)
    print("Fix Grok-Extracted Decision Nodes")
    print("=" * 70)

    # Step 1: Query thin decisions
    print("\n[1] Querying thin decisions from ArcadeDB ...")
    all_decisions = db_run("SELECT name, what, reasoning, @rid FROM Decision")

    thin_decisions = []
    for d in all_decisions:
        w = (d.get("what") or "").strip()
        r = (d.get("reasoning") or "").strip()

        is_thin = False
        if not r:
            is_thin = True
        if "[what you decided" in w.lower():
            is_thin = True
        if not w and not r:
            is_thin = True

        if is_thin:
            thin_decisions.append(d)

    print(f"  Total decisions: {len(all_decisions)}")
    print(f"  Thin decisions: {len(thin_decisions)}")

    if not thin_decisions:
        print("  No thin decisions to fix. Done.")
        return

    # Step 2: Load Grok conversations
    print("\n[2] Loading Grok export ...")
    grok_json = find_grok_json()
    if not grok_json:
        print("  ERROR: Could not find Grok export JSON in brain-inbox. Provide path or ensure file exists.")
        return
    convos = load_grok_data(grok_json)
    conv_index = build_conversation_index(convos)

    # Step 3: Match and fix
    print("\n[3] Matching decisions to conversations and extracting ...")
    stats = {"total": len(thin_decisions), "updated": 0, "still_thin": 0, "errors": 0, "no_match": 0}

    for dec in thin_decisions:
        name = dec["name"]
        rid = dec["@rid"]
        old_what = (dec.get("what") or "").strip()
        old_reasoning = (dec.get("reasoning") or "").strip()

        topic = extract_topic(name)
        dec_num = extract_decision_number(name)

        print(f"\n  [{topic}] Decision {dec_num} ({rid})")
        print(f"    Old what: {old_what[:80]!r}")

        match, score = find_matching_conversation(topic, conv_index)

        if match is None:
            print(f"    -> No matching conversation found")
            stats["no_match"] += 1
            stats["still_thin"] += 1
            continue

        print(f"    -> Matched: {match['title']!r} (score={score:.2f})")

        new_what, new_reasoning = extract_decision_from_conversation(match, dec_num)

        final_what = old_what
        final_reasoning = old_reasoning
        should_update = False

        if new_what and (
            not old_what
            or "[what you decided" in old_what.lower()
            or len(old_what) < 15
        ):
            final_what = new_what
            should_update = True

        if new_reasoning and not old_reasoning:
            final_reasoning = new_reasoning
            should_update = True

        if not should_update:
            print(f"    -> No improvement available, skipping")
            stats["still_thin"] += 1
            continue

        print(f"    -> New what: {sanitize(final_what)[:100]!r}")
        print(f"    -> New reasoning: {sanitize(final_reasoning)[:100]!r}")

        try:
            ok = db_update_by_rid(rid, final_what, final_reasoning)
            if ok:
                print(f"    -> Updated successfully")
                stats["updated"] += 1
            else:
                stats["errors"] += 1
                stats["still_thin"] += 1
        except Exception as e:
            print(f"    -> EXCEPTION: {e}")
            stats["errors"] += 1
            stats["still_thin"] += 1

    # Step 4: Report
    print("\n" + "=" * 70)
    print("REPORT")
    print("=" * 70)
    print(f"  Total thin decisions found:  {stats['total']}")
    print(f"  Updated with new content:    {stats['updated']}")
    print(f"  No matching conversation:    {stats['no_match']}")
    print(f"  Still thin (no improvement): {stats['still_thin']}")
    print(f"  Errors during update:        {stats['errors']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
