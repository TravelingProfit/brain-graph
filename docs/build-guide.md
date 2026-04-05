# Second Brain — Build Guide

A step-by-step guide to building your personal knowledge graph from scratch.

---

## Overview

The build happens in four phases:

| Phase | Name | What Happens |
|---|---|---|
| 0 | Infrastructure | Install ArcadeDB, create database, run schema, verify MCP, set up inbox |
| 1 | Seed the Graph | Process your highest-signal documents first (project specs, curated notes) |
| 2 | Conversations | Process AI conversation exports (Claude, ChatGPT, Grok, etc.) |
| 3 | Everything Else | Maps, notebooks, YouTube data, miscellaneous sources |
| 4 | Ongoing | Drop files, process, review, maintain |

Each phase builds on the last. Don't skip ahead — the graph needs a solid skeleton before you attach conversation data to it.

---

## Phase 0: Infrastructure

### 1. Start ArcadeDB

```bash
docker-compose up -d
```

Or manually:

```bash
docker run -d \
  --name second-brain-db \
  -p 2480:2480 -p 2424:2424 \
  -v ~/second-brain-data:/home/arcadedb/databases \
  -e JAVA_OPTS="-Darcadedb.server.rootPassword=YOUR_PASSWORD_HERE" \
  arcadedata/arcadedb:latest
```

### 2. Create the database

Open ArcadeDB Studio at http://localhost:2480. Create a new database called `secondbrain`.

### 3. Run the schema

Execute `schema/second-brain-schema.sql` in the Studio console (use SQL language mode). All statements use `IF NOT EXISTS` — safe to re-run.

### 4. Verify MCP

Connect your agent framework to the ArcadeDB MCP endpoint:
- From host: `http://localhost:2480/api/v1/mcp`
- From Docker: `http://host.docker.internal:2480/api/v1/mcp`
- Auth: HTTP Basic (base64-encode `root:YOUR_PASSWORD`)

Test by calling `list_databases` and `server_status`.

### 5. Create the inbox

```bash
mkdir -p ~/brain-inbox/{projects,claude,grok,maps,other}
mkdir -p ~/brain-inbox/classified/{deep,light,skip}
mkdir -p ~/brain-inbox/{processed,failed}
```

### 6. Install embedding model (optional)

Choose one of:
- **Ollama:** `ollama pull nomic-embed-text`
- **API:** Configure OpenRouter, OpenAI, or another provider in `.env`

---

## Phase 1: Seed the Graph

### Data Source Strategy

Process your highest-signal sources first. The order matters:

1. **Project docs and specs** — Pre-distilled, highest signal density. One good project spec can produce 30+ Concepts, 10+ Decisions, and multiple Person/Project nodes. These build the graph's skeleton.

2. **Curated notes / memory files** — Already filtered by you. Seeds the Person and Project nodes that project docs reference. Processing these second means the extractor can link to existing nodes instead of creating orphans.

3. **AI conversations** — Adds temporal depth and fills gaps. Needs heavy triage (maybe 30% is worth full extraction). Processing after the skeleton exists means better dedup matching.

4. **Maps, notebooks, other sources** — Lower volume, variable signal. Process last.

### Why This Order

If you process AI conversations first (your largest corpus), you'll create hundreds of disconnected nodes with no skeleton to attach to. Processing project docs first creates the gravitational wells — Project, Person, and core Concept nodes — that everything else naturally links into.

### What to Do

1. Drop project docs (markdown, text) into `~/brain-inbox/projects/`
2. Drop curated notes into `~/brain-inbox/other/` (or a custom subdirectory)
3. Process through triage (all should classify as DEEP)
4. Run extraction
5. Open ArcadeDB Studio and visually inspect the graph
6. Spot-check: Do key entities exist? Do Decisions have reasoning? Do edges have labels?
7. Adjust extraction prompts if quality is off

**Expected output:** 100-200 nodes, 300-500 edges from a handful of well-written project docs.

---

## Phase 2: AI Conversations

### Preprocessing

Most AI platforms export conversations as a single large JSON file. Split it into individual files first:

```bash
python scripts/split_claude.py conversations.json ~/brain-inbox/claude/
```

### Triage

Run triage to classify each conversation:

```bash
python scripts/triage_claude.py
```

This sorts files into:
- **DEEP** — Full entity extraction (architecture discussions, project planning, decisions)
- **LIGHT** — Summary + embedding only (debugging, how-to, reference lookups)
- **SKIP** — No processing (format conversions, test messages, abandoned chats)

**Review the SKIP pile.** Make sure nothing valuable was dropped. The triage rule is: when in doubt, go LIGHT, never SKIP.

### Extraction

Process DEEP conversations through full extraction, LIGHT through summary creation:

```bash
# DEEP: full entity extraction
python scripts/extract_claude_batch.py

# LIGHT: summary Artifacts
python scripts/extract_claude_light.py
```

### Embedding backfill

After all nodes are created, generate embeddings:

```bash
python scripts/embedding_backfill.py
```

This may take time depending on your embedding provider. API-based providers are fast. Local (Ollama on CPU) may take hours for large corpora — run it overnight.

---

## Phase 3: Everything Else

Process remaining sources:

- **Google Maps:** `python scripts/process_maps.py` — Creates Artifact nodes for saved places with pricing/assessment data from notes.
- **Other sources:** Write a processor or manually create extraction JSON and feed it to `graph_writer.py`.

After all sources are processed:
- Connect all agent instances to the MCP server
- Install the synthesize skill/behaviour configuration
- Test with "what do I know about X?" queries

---

## Phase 4: Ongoing Operations

The system is self-sustaining. New knowledge enters by dropping files into `~/brain-inbox/`.

| Task | Frequency |
|---|---|
| Drop new data into brain-inbox | Continuous |
| Process new files through triage + extract | As needed |
| Embedding backfill for new nodes | After processing |
| Decision review (flag stale decisions) | Monthly |
| Graph health check (orphans, missing embeddings) | Weekly |
| Dedup consolidation (merge near-duplicates) | Monthly |

---

## Schema Explanation

### Why 5 Vertex Types

| Type | What It Captures | Example |
|---|---|---|
| **Concept** | Atomic units of knowledge — ideas, technologies, techniques, principles | "Kubernetes", "Backpressure", "MCP Protocol" |
| **Artifact** | Immutable source records — the raw material that was processed | A conversation transcript, a build spec, a saved place list |
| **Decision** | Deliberate choices with reasoning — the highest-value node type | "Chose ArcadeDB over Neo4j because multi-model eliminates polyglot persistence" |
| **Person** | Anyone referenced across your knowledge | Collaborators, advisors, contacts |
| **Project** | Grouping contexts — gravitational wells that pull related nodes into orbit | "My Project Alpha", "Side Project Beta" |

**Deliberately excluded:**
- **Tags** — Weak substitute for graph structure. If you need categorization, use edges.
- **Events/Locations** — These can be represented as Concepts or Artifact metadata. Adding more vertex types increases schema complexity without proportional query value.
- **Hierarchy types** — Let structure emerge from edges rather than baking in a taxonomy.

You can always add types later. Starting with fewer types and more flexible edges keeps the schema simple.

### Why 6 Edge Types

| Edge | From -> To | Purpose |
|---|---|---|
| **RELATES_TO** | Concept -> Concept | Semantic links with specific labels (implements, replaces, depends_on, is_aspect_of, alternative_to, etc.) |
| **MENTIONS** | Artifact -> any | What a source document references. Context property explains how. |
| **LED_TO** | Decision/Concept -> Decision/Concept | Causal chains. "Choosing X led to simplifying Y." |
| **PART_OF** | any -> Project | Contextual grouping. Everything that belongs to a project. |
| **DERIVED_FROM** | any -> Artifact | Provenance tracking. Where did this knowledge come from? |
| **CONTRADICTS** | Artifact -> Artifact | Cross-source conflict tracking. When two sources disagree. |

**Critical:** Vague edges are useless. Every RELATES_TO edge must have a specific `label` property. Every MENTIONS edge must have a `context` property explaining how the artifact references the entity.

### Full-Text Indexes

Lucene indexes are created on all searchable text fields. Use `CONTAINSTEXT` for single-word search and `ILIKE` for phrase matching. See the [Known Issues](#known-issues-and-workarounds) section for details.

---

## Decision Log

Architectural decisions made during the design and build, preserved for reference.

| # | Decision | Alternatives Considered | Reasoning |
|---|---|---|---|
| 1 | ArcadeDB as sole database | Neo4j, separate vector DB + graph DB, PostgreSQL + pgvector | Multi-model (graph + document + vector + full-text) eliminates polyglot persistence. Built-in MCP server. One thing to learn, one thing to back up. |
| 2 | Five vertex types (Concept, Artifact, Decision, Person, Project) | Fewer types with more properties; more types (Tag, Event, Location) | Five covers the needed query patterns. Deliberately excluded Tags (weak graph substitute) and fixed hierarchy. Can always add types later. |
| 3 | Skills over system prompts for agent integration | Baked-in system prompts; single monolithic prompt | Skills follow progressive disclosure. Agent loads only what it needs. Cheaper, cleaner context management. |
| 4 | Filesystem inbox interface (`~/brain-inbox/`) | API endpoint; direct database writes; message queue | Any tool can write a file. Zero integration effort. Unix philosophy. |
| 5 | ArcadeDB's built-in MCP server (raw query/execute_command) | Custom MCP server wrapping ArcadeDB with structured CRUD tools | Simpler. No custom code to maintain. Agent composes SQL from templates. Use what exists before building. |
| 6 | Project docs processed first, not conversations | Conversations first (largest corpus); all sources simultaneously | Project docs are pre-distilled, highest signal density. They build a skeleton that conversations attach to. Better dedup when matching incoming entities against existing nodes. |
| 7 | Accept slow CPU embeddings rather than skip them | Skip embeddings entirely; rent GPU time | Embeddings enable vector similarity search. Value justifies batch runs. No external dependency if using local model. |
| 8 | Triage as a separate skill, not inline in extract | Combined triage+extract; triage as a pre-processing script | Separation keeps each skill focused. Triage is cheap (fast model, minimal tokens). Extract is expensive. Don't pay extract costs on content that should be skipped. |
| 9 | Accept initial duplicates, consolidate later | Strict dedup with embedding similarity on every insert | Strict dedup blocks the harvester on a hard problem. Creating nodes is cheap. Merging later is easier than splitting after a bad merge. Name + alias matching catches obvious dupes; near-dupes get flagged. |
| 10 | SQL for ArcadeDB queries over Cypher | Cypher for all graph operations; mixed SQL + Cypher | ArcadeDB's SQL has better full-text search support. Cypher available for complex traversals if needed. |
| 11 | Single harvester agent, not distributed processing | Multiple harvester agents; external pipeline (Temporal, Airflow) | Keep it simple. One agent, sequential processing. Volume doesn't justify distributed architecture. |
| 12 | API embeddings over local model | Install Ollama locally, use Docker Ollama, skip embeddings | If no local GPU is available, API embeddings (e.g., OpenRouter at ~$0.01/M tokens) are fast and cheap. No local dependency. |
| 13 | streaming-http MCP transport | SSE, stdio via wrapper | ArcadeDB uses JSON-RPC over HTTP POST. Most agent frameworks support streaming-http natively. |
| 14 | Single-field Lucene indexes over multi-field FULL_TEXT | Multi-field FULL_TEXT (broken in some versions), skip full-text | Multi-field FULL_TEXT in ArcadeDB may not backfill existing data. Single-field ENGINE LUCENE works reliably. |
| 15 | behaviour.md for agent integration | Knowledge vector store, system prompt editing | behaviour.md auto-prepends to the agent system prompt. Correct layer for behavioral instructions vs retrieval context. |
| 16 | Batch Python scripts for bulk processing | Agent harvester for all files | Hundreds of source files need automated batch processing. Scripts are faster and more reliable than single-file agent runs. Agent harvester is for ongoing single-file processing. |
| 17 | ILIKE as primary text search over CONTAINSTEXT | CONTAINSTEXT only | ILIKE handles phrase matching and partial strings. CONTAINSTEXT does word-level tokenization. ILIKE is more predictable for multi-word queries. |
| 18 | Idempotent processing with content_hash dedup | No dedup (trust the user); embedding-based dedup | Content hash is cheap and deterministic. Prevents re-processing the same file. Embedding-based dedup is expensive and error-prone at insert time. |

---

## Known Issues and Workarounds

### Full-Text Indexes (CONTAINSTEXT)

**Issue:** Multi-field `FULL_TEXT` indexes in ArcadeDB (observed in v26.4.1) may not backfill existing data when created after nodes already exist.

**Fix:** Use single-field indexes with `ENGINE LUCENE`:
```sql
CREATE INDEX ON Concept(name) FULL_TEXT ENGINE LUCENE;
CREATE INDEX ON Concept(description) FULL_TEXT ENGINE LUCENE;
```

**Workaround:** For phrase-level search (e.g., "agent zero" as a phrase), use `ILIKE '%agent zero%'` instead of `CONTAINSTEXT`. CONTAINSTEXT does word-level tokenization, so `CONTAINSTEXT 'agent zero'` matches any node containing both words anywhere, not the phrase.

### ILIKE vs CONTAINSTEXT

| Use Case | Use This | Why |
|---|---|---|
| Single word search | `CONTAINSTEXT 'kubernetes'` | Uses Lucene index, fast |
| Phrase search | `ILIKE '%my exact phrase%'` | CONTAINSTEXT tokenizes words separately |
| Partial match | `ILIKE '%partial%'` | CONTAINSTEXT requires full words |
| Case-insensitive | Either | Both are case-insensitive |

### ArcadeDB SQL Limitations

- **No UNION/UNION ALL** — Run separate queries per vertex type and combine results in your application/agent
- **No subqueries in FROM clause** — Use multi-step queries instead
- **Apostrophes in strings** — Escape carefully (`\'`) or strip them. The `graph_writer.py` handles this.
- **No `SELECT FROM V`** — ArcadeDB does not support querying all vertex types at once. Query each type individually.
- **Date comparison** — Use string comparison for dates: `WHERE created_at < '2025-10-01'`

### Orphan Concepts

Some Concept nodes will have no edges after initial extraction. This is normal — they represent valid knowledge that hasn't been connected yet. As more content enters the graph, these orphans naturally gain edges. Run periodic consolidation passes to link them.

### Thin Decisions

Some auto-extracted Decision nodes may have incomplete reasoning fields. This happens when the extraction detects a decision pattern ("chose X over Y") but the full context isn't captured. Enrich these by re-reading the source artifact.
