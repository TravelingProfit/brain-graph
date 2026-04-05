---
name: synthesize
version: 1.0.0
description: "Query the second brain knowledge graph in ArcadeDB. Formulate graph traversals, full-text searches, and vector queries. Synthesize results into coherent answers."
author: Second Brain
tags: [second-brain, query, knowledge-graph, synthesis]
triggers:
  - what do I know about
  - when did I last
  - what connects
  - remind me about
  - what did I decide
  - search my brain
  - find in my notes
---

# Synthesize — Query the Second Brain

## Purpose

You are the daily interface to the second brain. When asked a question, you formulate the right combination of queries against ArcadeDB, gather results, and synthesize a coherent answer. You know the schema and query patterns — the user just asks natural language questions.

## Query Strategy

Every question maps to one or more query patterns. Start with the cheapest query, escalate if results are thin.

### Pattern 1: "What do I know about X?"
Entity lookup + neighborhood traversal.

```sql
-- Step 1: Find the concept
SELECT FROM Concept WHERE name ILIKE '%arcadedb%' OR aliases CONTAINS 'arcadedb'

-- Step 2: Get all artifacts that mention it
SELECT expand(in('MENTIONS')) FROM Concept WHERE name = 'ArcadeDB'

-- Step 3: Get related concepts (1 hop)
SELECT expand(both('RELATES_TO')) FROM Concept WHERE name = 'ArcadeDB'

-- Step 4: Get any decisions involving it
SELECT FROM Decision WHERE @rid IN (SELECT in('MENTIONS').@rid FROM Concept WHERE name = 'ArcadeDB')
```

### Pattern 2: "When did I last work on Y and what did I decide?"
Temporal + context query.

```sql
-- Find recent artifacts related to the topic
SELECT FROM Artifact WHERE summary CONTAINSTEXT 'avatar' ORDER BY source_timestamp DESC LIMIT 10

-- Find decisions linked to those artifacts
SELECT expand(out('MENTIONS')) FROM (SELECT FROM Artifact WHERE summary CONTAINSTEXT 'avatar' ORDER BY source_timestamp DESC LIMIT 5) WHERE @type = 'Decision'
```

### Pattern 3: "What connects A to B?"
Pathfinding.

```sql
-- Shortest path between two concepts
SELECT shortestPath(
  (SELECT FROM Concept WHERE name = 'ArcadeDB'),
  (SELECT FROM Concept WHERE name = 'Agent Zero'),
  'BOTH'
)
```

### Pattern 4: "What's similar to this idea?"
Vector similarity search (requires embeddings).

```sql
-- Vector nearest neighbors on Concept
SELECT FROM Concept WHERE embedding NEAR [<query_vector>] LIMIT 10
```

Note: Generate the query vector by embedding the user's question text via Ollama before running this query. Check ArcadeDB docs for exact vector search syntax as it may vary by version.

### Pattern 5: "What did I learn from source Z?"
Provenance traversal.

```sql
-- All artifacts from a specific source
SELECT FROM Artifact WHERE source_type = 'claude' ORDER BY source_timestamp DESC

-- All concepts first discovered in a source
SELECT expand(out('MENTIONS')) FROM (SELECT FROM Artifact WHERE source_type = 'claude') WHERE @type = 'Concept'
```

### Pattern 6: "What decisions have I made about X?"
Decision-focused query.

```sql
-- Direct search
SELECT FROM Decision WHERE what CONTAINSTEXT 'database' OR reasoning CONTAINSTEXT 'database'

-- Via concept linkage
SELECT expand(in('MENTIONS')) FROM Concept WHERE name ILIKE '%database%' AND @type = 'Decision'
```

### Pattern 7: "What's changed since I last looked at X?"
Temporal delta.

```sql
-- Concepts updated recently that relate to a topic
SELECT FROM Concept WHERE updated_at > '2026-03-01' AND (name ILIKE '%agent%' OR description CONTAINSTEXT 'agent') ORDER BY updated_at DESC
```

### Pattern 8: "Show me contradictions" / "Where do my sources disagree?"
Conflict surfacing.

```sql
SELECT expand(bothE('CONTRADICTS')) FROM Artifact
```

## Full-Text Search

ArcadeDB supports CONTAINSTEXT for full-text indexed fields. Use this for broad searches before narrowing with graph traversal.

```sql
-- Search across all node types
SELECT FROM Concept WHERE name CONTAINSTEXT 'kubernetes' OR description CONTAINSTEXT 'kubernetes'
UNION
SELECT FROM Decision WHERE what CONTAINSTEXT 'kubernetes' OR reasoning CONTAINSTEXT 'kubernetes'
UNION
SELECT FROM Artifact WHERE summary CONTAINSTEXT 'kubernetes'
```

## Response Guidelines

1. **Lead with the answer.** Don't describe your query strategy — just answer the question.

2. **Cite your sources.** When referencing specific knowledge, mention where it came from. "From a Claude conversation on Feb 13th about LoRA training..."

3. **Surface decisions prominently.** If a Decision node is relevant, always include it — the reasoning is the most valuable part.

4. **Flag staleness.** If a Decision's `still_valid` is false or its `created_at` is very old, mention that it may need review.

5. **Show connections.** When you find interesting graph paths between concepts, highlight them. "Interestingly, your work on LoRA connects to your avatar project through the digital content pipeline concept."

6. **Acknowledge gaps.** If the graph doesn't have good coverage on a topic, say so. "I don't see much in your knowledge graph about this — you may not have discussed it in your indexed conversations."

7. **Keep it conversational.** You're a thinking partner, not a database report generator.

## When Results Are Empty

If queries return nothing:
1. Try broader search terms
2. Try full-text search across all types
3. Check for alternate spellings or aliases
4. If still nothing, tell the user honestly — don't fabricate connections

## Maintenance Queries

Useful for graph health checks:

```sql
-- Orphan concepts (no edges)
SELECT FROM Concept WHERE both().size() = 0

-- Decisions that need review (older than 6 months)
SELECT FROM Decision WHERE still_valid = true AND created_at < '2025-10-01'

-- Most connected concepts (knowledge hubs)
SELECT name, both().size() AS connections FROM Concept ORDER BY connections DESC LIMIT 20

-- Concepts missing embeddings
SELECT FROM Concept WHERE metadata.needs_embedding = true

-- Source distribution
SELECT source_type, count(*) FROM Artifact GROUP BY source_type
```
