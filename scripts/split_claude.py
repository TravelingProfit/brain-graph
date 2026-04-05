#!/usr/bin/env python3
"""Split a Claude AI export JSON into individual conversation files."""
import json
import os
import sys


def split_claude_export(input_file, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading {input_file}...")
    with open(input_file, 'r', encoding='utf-8') as f:
        conversations = json.load(f)

    print(f"Total conversations in export: {len(conversations)}")

    skipped = 0
    written = 0

    for conv in conversations:
        if not conv.get('chat_messages'):
            skipped += 1
            continue

        uuid = conv['uuid']
        filepath = os.path.join(output_dir, f"{uuid}.json")

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(conv, f, indent=2, ensure_ascii=False)
        written += 1

    print(f"Written: {written}, Skipped (empty): {skipped}")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python split_claude.py <conversations.json> <output_dir>")
        print("Example: python split_claude.py conversations.json ~/brain-inbox/claude/")
        sys.exit(1)
    split_claude_export(sys.argv[1], sys.argv[2])
