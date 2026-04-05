"""
Extract Grok conversations containing Thai text into a review folder.
Scans a Grok export JSON and saves Thai-containing conversations
with an index CSV for review.
"""
import json
import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import cfg

OUTPUT_DIR = Path(os.path.join(cfg.BRAIN_INBOX, "grok-thai-review"))

THAI_RE = re.compile(r"[\u0E00-\u0E7F]")
ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+")


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


def has_thai(text: str) -> bool:
    return bool(THAI_RE.search(text))


def strip_thai(text: str) -> str:
    """Remove Thai characters, collapse whitespace."""
    cleaned = THAI_RE.sub("", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def count_ascii_words(text: str) -> int:
    return len(ASCII_WORD_RE.findall(text))


def get_create_time(entry: dict) -> str:
    """Extract human-readable create_time from conversation."""
    return entry.get("conversation", {}).get("create_time", "")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Determine input path
    input_path = sys.argv[1] if len(sys.argv) > 1 else find_grok_json()
    if not input_path or not os.path.exists(input_path):
        print("ERROR: Grok export JSON not found.")
        print("Usage: python extract_grok_thai.py [<path_to_grok_json>]")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    conversations = data.get("conversations", [])
    print(f"Total conversations in export: {len(conversations)}")

    rows = []

    for entry in conversations:
        conv = entry.get("conversation", {})
        conv_id = conv.get("id", "unknown")
        title = conv.get("title", "") or ""
        responses = entry.get("responses", [])

        texts_to_check = [title]
        for r in responses:
            msg = r.get("response", {}).get("message", "") or ""
            texts_to_check.append(msg)

        combined = "\n".join(texts_to_check)
        if not has_thai(combined):
            continue

        fname = f"{conv_id}.json"
        out_path = OUTPUT_DIR / fname
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)

        human_msgs = []
        for r in responses:
            resp = r.get("response", {})
            if resp.get("sender", "").lower() == "human":
                human_msgs.append(resp.get("message", "") or "")

        human_combined = " ".join(human_msgs)
        ascii_word_count = count_ascii_words(human_combined)
        has_english = ascii_word_count > 50

        preview = ""
        if human_msgs:
            preview = strip_thai(human_msgs[0])[:150]

        rows.append({
            "filename": fname,
            "title": title,
            "message_count": len(responses),
            "date": get_create_time(entry),
            "preview": preview,
            "has_english": str(has_english).lower(),
        })

    rows.sort(key=lambda r: r["has_english"], reverse=True)

    csv_path = OUTPUT_DIR / "_index.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "filename", "title", "message_count", "date", "preview", "has_english"
        ])
        writer.writeheader()
        writer.writerows(rows)

    english_count = sum(1 for r in rows if r["has_english"] == "true")
    print(f"Thai conversations saved: {len(rows)}")
    print(f"  With substantial English: {english_count}")
    print(f"  Thai-only: {len(rows) - english_count}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Index:  {csv_path}")


if __name__ == "__main__":
    main()
