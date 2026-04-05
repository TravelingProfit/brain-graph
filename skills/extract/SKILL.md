---
name: extract
version: 1.0.0
description: "Extract Concepts, Decisions, Persons, Projects, and edges from classified content. Write to ArcadeDB via MCP. Handles dedup and embedding generation."
author: Second Brain
tags: [second-brain, harvester, extraction, knowledge-graph]
triggers:
  - process classified content
  - extract entities
  - harvest knowledge
---

# Extract — Entity Extraction & Graph Writing

## Purpose

You receive content classified as DEEP or LIGHT by the triage skill. Your job is to extract structured knowledge and write it to ArcadeDB.

- **DEEP content:** Full extraction — Concepts, Decisions, Persons, Projects, edges, embeddings.
- **LIGHT content:** Create one Artifact node with a summary and embedding. Link to any existing Concepts/Projects that match. No heavy extraction.

## Extraction Rules

### What Is a Concept?
A Concept is an idea, term, technique, technology, or principle that you'd plausibly want to find again.

**IS a Concept:** "ArcadeDB", "LoRA training", "backpressure", "MCP protocol", "agent orchestration"
**NOT a Concept:** "lunch", "yesterday", "the file", "that thing" — generic nouns that carry no retrievable knowledge

**Granularity:** Create fine-grained concepts. "Python async" is better than "Python". Use RELATES_TO edges with label "is_aspect_of" to connect specific concepts to broader ones.

### What Is a Decision?
A Decision is a deliberate choice among alternatives with stated reasoning. The signal is usually "I chose X because Y" or "we're going with X over Y."

**IS a Decision:** "Chose ArcadeDB over Neo4j because multi-model eliminates polyglot persistence"
**NOT a Decision:** "I'll use Python" (no alternatives, no reasoning)

Decisions are your highest-value nodes. Be aggressive about detecting them. If someone explains WHY they did something, that's a Decision.

### What Is an Artifact?
Every piece of source content becomes exactly one Artifact node. The Artifact is the raw record — the conversation, document, or file that was processed. Everything else (Concepts, Decisions, edges) is extracted FROM the Artifact.

### Edge Labeling
Vague edges are nearly useless. Be specific:

**RELATES_TO labels:** "implements", "replaces", "contradicts", "extends", "depends_on", "is_aspect_of", "enables", "requires", "alternative_to", "similar_to"

**MENTIONS context:** Brief note on how the artifact references the entity. "Discussed as database option" not just empty.

## Deduplication

Before creating any Concept or Person node, check if it already exists:

```sql
-- Check for existing concept by name (exact match)
SELECT FROM Concept WHERE name = 'ArcadeDB'

-- Check for existing concept by alias
SELECT FROM Concept WHERE aliases CONTAINS 'arcadedb'

-- Check for existing person
SELECT FROM Person WHERE name = 'Wayne'
```

If a match is found:
- Do NOT create a duplicate
- DO create edges from the new Artifact to the existing node
- DO update the existing node's `updated_at` timestamp
- DO add any new aliases to the existing node's `aliases` list

If no exact match but you suspect a near-duplicate (e.g., "gRPC" vs "Google RPC"):
- Create the node anyway
- Add a note in metadata: `{"possible_duplicate": "gRPC"}`
- Periodic consolidation will handle merges later

## ArcadeDB Write Patterns

Use these query templates via the `execute_command` MCP tool.

### Create an Artifact
```sql
INSERT INTO Artifact SET
  name = 'Creating a digital avatar with LoRA',
  source_type = 'claude',
  source_path = 'brain-inbox/claude/conversation-17c0abf7.json',
  content_hash = 'sha256_of_content',
  summary = 'Discussion about training LoRA for digital avatar...',
  created_at = '2026-02-13T00:48:12Z',
  source_timestamp = '2026-02-13T00:48:12Z',
  metadata = {"message_count": 24, "source_uuid": "9993b56d-..."}
```

### Create a Concept
```sql
INSERT INTO Concept SET
  name = 'LoRA Training',
  description = 'Low-Rank Adaptation technique for fine-tuning...',
  created_at = sysdate(),
  updated_at = sysdate(),
  source = 'claude',
  aliases = ['LoRA', 'Low-Rank Adaptation'],
  metadata = {}
```

### Create a Decision
```sql
INSERT INTO Decision SET
  name = 'Use LoRA over full fine-tuning for avatar',
  what = 'Chose LoRA for creating digital avatar',
  alternatives = ['full fine-tuning', 'DreamBooth', 'textual inversion'],
  reasoning = 'LoRA is faster, requires less VRAM, and produces...',
  confidence = 'high',
  still_valid = true,
  created_at = sysdate(),
  metadata = {}
```

### Create Edges
```sql
-- Find nodes by name, create edge
CREATE EDGE MENTIONS FROM (SELECT FROM Artifact WHERE name = 'Creating a digital avatar with LoRA') TO (SELECT FROM Concept WHERE name = 'LoRA Training') SET context = 'Primary topic of conversation', created_at = sysdate()

CREATE EDGE PART_OF FROM (SELECT FROM Concept WHERE name = 'LoRA Training') TO (SELECT FROM Project WHERE name = 'Digital Avatar') SET role = 'core technology', created_at = sysdate()

CREATE EDGE RELATES_TO FROM (SELECT FROM Concept WHERE name = 'LoRA Training') TO (SELECT FROM Concept WHERE name = 'Stable Diffusion') SET label = 'used_with', weight = 0.8, created_at = sysdate()
```

## Source-Specific Parsing

### Claude AI JSON
```
Structure:
{
  "uuid": "...",
  "name": "conversation title",
  "created_at": "ISO timestamp",
  "chat_messages": [
    {
      "text": "plain text content",
      "sender": "human" | "assistant",
      "created_at": "ISO timestamp",
      "attachments": [],
      "files": []
    }
  ]
}
```

- Use `name` as the Artifact name
- Use `uuid` in metadata for provenance
- Use `created_at` as source_timestamp
- Process `text` field from each message (ignore `content` array — it's the same data with extra structure)
- Only extract from `sender: "human"` messages for decisions and intent; use `sender: "assistant"` for technical concepts and explanations

### OpenClaw Markdown
- Headers → Concept or Project names
- Bullet points → properties or separate Artifacts depending on substance
- "We use X because Y" patterns → Decision nodes
- Trust this content more — it's already curated

### Google Maps CSV
- Each row → Artifact (type: place)
- Title → Artifact name
- Note field → parse for: prices, assessments, source attributions, status
- URL → store in metadata
- Infer a Project node from the list name (e.g., "Chiang Mai Condo Search")

## Embedding Generation

After creating nodes, generate embeddings via OpenRouter API (Qwen3 Embedding 8B, 1024 dimensions) for:
- Every Concept (embed: name + description)
- Every Artifact (embed: summary)
- Every Decision (embed: name + what + reasoning)

### API Call Pattern

```
POST https://openrouter.ai/api/v1/embeddings
Headers:
  Authorization: Bearer <OPENROUTER_API_KEY>
  Content-Type: application/json

Body:
{
  "model": "qwen/qwen3-embedding-8b",
  "input": "text to embed"
}
```

Response contains `data[0].embedding` — a 1024-dimensional float array. Store this in the node's `embedding` property.

Cost: ~$0.01/million tokens — negligible for our volume.

Do NOT block on embedding failures. Create the node without embedding, flag it in metadata as `{"needs_embedding": true}`, and continue. A separate pass can backfill embeddings later.

## Idempotency

- Check `content_hash` before creating Artifacts — if it exists, skip the entire file
- Move processed files to `brain-inbox/processed/` on success
- Move failed files to `brain-inbox/failed/` with error details in a `.error` sidecar file
- Never leave a file in the classified directory after attempting processing

## Output

After processing a file, log:
- Nodes created: X Concepts, Y Decisions, Z Persons, W Projects, 1 Artifact
- Edges created: N total
- Duplicates found and linked: M
- Errors/warnings: any issues encountered
