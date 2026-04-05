#!/usr/bin/env python3
"""
Backfill embeddings for all nodes in the Second Brain.
Uses centralized config for embedding provider and ArcadeDB access.
"""
import json
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import cfg

BATCH_SIZE = cfg.EMBEDDING_BATCH_SIZE
SLEEP_BETWEEN = 0.5  # seconds between batches


def get_nodes_needing_embeddings():
    """Get all nodes that don't have embeddings yet."""
    nodes = []

    # Concepts: embed name + description
    records = cfg.arcadedb_query("SELECT @rid as rid, name, description FROM Concept WHERE embedding IS NULL OR embedding.size() = 0")
    for r in records:
        text = r.get("name", "")
        if r.get("description"):
            text += " - " + r["description"]
        nodes.append({"rid": r["rid"], "type": "Concept", "name": r["name"], "text": text})

    # Decisions: embed name + what + reasoning
    records = cfg.arcadedb_query("SELECT @rid as rid, name, what, reasoning FROM Decision WHERE embedding IS NULL OR embedding.size() = 0")
    for r in records:
        parts = [r.get("name", "")]
        if r.get("what"): parts.append(r["what"])
        if r.get("reasoning"): parts.append(r["reasoning"])
        nodes.append({"rid": r["rid"], "type": "Decision", "name": r["name"], "text": " - ".join(parts)})

    # Artifacts: embed name + summary
    records = cfg.arcadedb_query("SELECT @rid as rid, name, summary FROM Artifact WHERE embedding IS NULL OR embedding.size() = 0")
    for r in records:
        text = r.get("name", "")
        if r.get("summary"):
            text += " - " + r["summary"]
        nodes.append({"rid": r["rid"], "type": "Artifact", "name": r["name"], "text": text})

    return nodes


def update_embedding(rid, embedding):
    """Write embedding vector to a node by RID."""
    vec_str = json.dumps(embedding)
    sql = f"UPDATE {rid} SET embedding = {vec_str}"
    result = cfg.arcadedb_execute(sql)
    is_error = result.get("result", {}).get("isError", False)
    return not is_error


def backfill():
    nodes = get_nodes_needing_embeddings()
    total = len(nodes)
    print(f"\nNodes needing embeddings: {total}")
    if total == 0:
        print("All nodes already have embeddings!")
        return

    # Stats
    by_type = {}
    for n in nodes:
        by_type[n["type"]] = by_type.get(n["type"], 0) + 1
    for t, c in sorted(by_type.items()):
        print(f"  {t}: {c}")

    success = 0
    failed = 0

    # Process in batches
    for i in range(0, total, BATCH_SIZE):
        batch = nodes[i:i+BATCH_SIZE]
        texts = [n["text"][:2000] for n in batch]  # Truncate very long texts

        embeddings = cfg.get_embedding(texts)
        if embeddings is None:
            print(f"  Batch {i//BATCH_SIZE + 1} FAILED - API error")
            failed += len(batch)
            time.sleep(2)  # Back off on error
            continue

        for j, node in enumerate(batch):
            ok = update_embedding(node["rid"], embeddings[j])
            if ok:
                success += 1
            else:
                failed += 1

        done = min(i + BATCH_SIZE, total)
        print(f"  [{done}/{total}] {success} embedded, {failed} failed", end="\r")

        if i + BATCH_SIZE < total:
            time.sleep(SLEEP_BETWEEN)

    print(f"\n\nDone! {success} embedded, {failed} failed out of {total} total")


if __name__ == "__main__":
    backfill()
