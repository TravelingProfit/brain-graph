# Second Brain — Operations Template

Fill in this template for your own deployment. Replace all `<placeholder>` values with your actual configuration.

---

## 1. ArcadeDB Access

| Item | Value |
|---|---|
| Studio URL | http://localhost:2480 |
| MCP endpoint (from host) | http://localhost:2480/api/v1/mcp |
| MCP endpoint (from Docker) | http://host.docker.internal:2480/api/v1/mcp |
| Auth | HTTP Basic, `root:<YOUR_PASSWORD>` |
| Auth header (base64) | `Authorization: Basic <BASE64_OF_root:YOUR_PASSWORD>` |
| Database name | secondbrain |
| Docker container name | `<YOUR_CONTAINER_NAME>` |
| Data volume | `<PATH_TO_DATA_VOLUME>` |

### Generate Your Auth Header

```bash
echo -n "root:YOUR_PASSWORD" | base64
# Use the output as your Authorization header value
```

---

## 2. Agent Integration

### MCP Configuration

Add to your agent framework's MCP settings:

```json
{
  "mcpServers": {
    "arcadedb": {
      "url": "http://host.docker.internal:2480/api/v1/mcp",
      "type": "streaming-http",
      "headers": {
        "Authorization": "Basic <YOUR_BASE64_CREDENTIALS>"
      }
    }
  }
}
```

If your agent runs on the host (not in Docker), use `http://localhost:2480/api/v1/mcp` instead.

### behaviour.md Template

Place in your agent's memory/prompt directory (e.g., `memory/default/behaviour.md` for Agent Zero):

```markdown
## Second Brain Integration

You have access to a personal knowledge graph via the ArcadeDB MCP server.
The database is called `secondbrain` and contains:

- **Concepts** — ideas, technologies, techniques, principles
- **Decisions** — choices with reasoning and alternatives
- **Artifacts** — source documents, conversations, maps
- **Projects** — <LIST YOUR PROJECTS HERE>
- **Persons** — <LIST KEY PEOPLE HERE>

### When to Query the Brain

When the user asks about:
- What they know about a topic
- What they decided and why
- What connects two ideas
- Project status or history
- People and their context

### How to Query

Use the ArcadeDB MCP tools:
- `query` tool for SELECT statements (read)
- `execute_command` tool for INSERT/UPDATE/CREATE EDGE (write)
- Always specify `database: "secondbrain"` and `language: "sql"`

### Query Patterns

Use ILIKE for phrase search, CONTAINSTEXT for single-word search:

```sql
-- Find a concept
SELECT name, description FROM Concept WHERE name ILIKE '%search term%'

-- Find decisions about a topic
SELECT name, what, reasoning FROM Decision WHERE name ILIKE '%topic%'

-- What artifacts mention a concept
SELECT expand(in('MENTIONS')) FROM Concept WHERE name = 'Topic Name'

-- Related concepts
SELECT expand(both('RELATES_TO')) FROM Concept WHERE name = 'Topic Name'

-- Everything in a project
SELECT expand(in('PART_OF')) FROM Project WHERE name = 'My Project'
```

### Response Guidelines

- Lead with the answer, not the query strategy
- Surface Decisions prominently — the reasoning is the most valuable part
- Flag stale decisions (older than 6 months with still_valid = true)
- Acknowledge gaps honestly if the graph has no coverage
```

---

## 3. Query Reference

### Quick Lookups

```sql
-- Find a concept
SELECT name, description FROM Concept WHERE name ILIKE '%search term%'

-- Find decisions about a topic
SELECT name, what, reasoning, confidence FROM Decision
WHERE name ILIKE '%topic%' OR what ILIKE '%topic%' OR reasoning ILIKE '%topic%'

-- Find a person
SELECT name, context, relationship FROM Person WHERE name ILIKE '%name%'

-- Find artifacts from a source
SELECT name, source_type, summary FROM Artifact WHERE source_type = 'claude'

-- Find a project
SELECT name, description, status FROM Project WHERE name ILIKE '%project%'
```

### Graph Traversal

```sql
-- What artifacts mention a concept
SELECT expand(in('MENTIONS')) FROM Concept WHERE name = 'My Concept'

-- What concepts relate to another
SELECT expand(both('RELATES_TO')) FROM Concept WHERE name = 'My Concept'

-- Everything linked to a project
SELECT expand(in('PART_OF')) FROM Project WHERE name = 'My Project'

-- Shortest path between two nodes
SELECT shortestPath(
  (SELECT FROM Concept WHERE name = 'Concept A'),
  (SELECT FROM Concept WHERE name = 'Concept B'),
  'BOTH'
)
```

### Temporal Queries

```sql
-- Recent artifacts about a topic
SELECT name, summary, source_timestamp FROM Artifact
WHERE summary ILIKE '%topic%' ORDER BY source_timestamp DESC LIMIT 10

-- Decisions that mention something, ordered by date
SELECT name, what, created_at FROM Decision
WHERE what ILIKE '%topic%' ORDER BY created_at DESC

-- Recently updated concepts
SELECT name, updated_at FROM Concept
WHERE updated_at > '2026-01-01' ORDER BY updated_at DESC LIMIT 20
```

### Full-Text Search (Lucene)

```sql
-- Single-word search via Lucene index (fast)
SELECT name FROM Concept WHERE description CONTAINSTEXT 'kubernetes'
SELECT name FROM Decision WHERE reasoning CONTAINSTEXT 'database'
SELECT name FROM Artifact WHERE summary CONTAINSTEXT 'architecture'

-- Phrase search (use ILIKE, not CONTAINSTEXT)
SELECT name FROM Concept WHERE name ILIKE '%agent zero%'
```

### Health Check Queries

```sql
-- Node counts per type
SELECT count(*) as cnt FROM Concept
SELECT count(*) as cnt FROM Decision
SELECT count(*) as cnt FROM Artifact
SELECT count(*) as cnt FROM Project
SELECT count(*) as cnt FROM Person

-- Edge counts per type
SELECT count(*) as cnt FROM MENTIONS
SELECT count(*) as cnt FROM PART_OF
SELECT count(*) as cnt FROM RELATES_TO
SELECT count(*) as cnt FROM LED_TO
SELECT count(*) as cnt FROM DERIVED_FROM
SELECT count(*) as cnt FROM CONTRADICTS

-- Most connected concepts
SELECT name, both().size() AS connections FROM Concept ORDER BY connections DESC LIMIT 20

-- Orphan nodes (no edges)
SELECT name FROM Concept WHERE both().size() = 0

-- Decisions needing review (older than 6 months)
SELECT name, what, created_at FROM Decision
WHERE still_valid = true AND created_at < '2025-10-01'

-- Nodes missing embeddings
SELECT name FROM Concept WHERE embedding IS NULL OR embedding.size() = 0

-- Source distribution
SELECT source_type, count(*) as cnt FROM Artifact GROUP BY source_type ORDER BY cnt DESC
```

### Write Operations

```sql
-- Create a concept
INSERT INTO Concept SET
  name = 'My New Concept',
  description = 'What this concept means...',
  created_at = sysdate(),
  updated_at = sysdate(),
  source = 'manual',
  aliases = ['alias1', 'alias2'],
  metadata = {}

-- Create a decision
INSERT INTO Decision SET
  name = 'Chose X over Y',
  what = 'Chose X for the project',
  alternatives = ['Y', 'Z'],
  reasoning = 'X is simpler and meets our requirements...',
  confidence = 'high',
  still_valid = true,
  created_at = sysdate(),
  metadata = {}

-- Create an edge
CREATE EDGE RELATES_TO FROM
  (SELECT FROM Concept WHERE name = 'Concept A') TO
  (SELECT FROM Concept WHERE name = 'Concept B')
  SET label = 'depends_on', created_at = sysdate()

-- Link an artifact to a concept
CREATE EDGE MENTIONS FROM
  (SELECT FROM Artifact WHERE name = 'My Document') TO
  (SELECT FROM Concept WHERE name = 'My Concept')
  SET context = 'Discussed as primary approach', created_at = sysdate()
```

---

## 4. Maintenance Schedule

| Task | Frequency | How |
|---|---|---|
| Drop new data | Continuous | Add files to `brain-inbox/` subdirectories |
| Process new files | As needed | Run appropriate processing script |
| Embedding backfill | After new nodes added | `python scripts/embedding_backfill.py` |
| Decision review | Monthly | Query for decisions older than 6 months with `still_valid = true` |
| Orphan cleanup | Monthly | Check for concepts with no edges, link or remove |
| Graph health check | Weekly | Run health check queries above |
| Dedup consolidation | Monthly | Review near-duplicate Concepts, merge manually |
| ArcadeDB backup | Weekly | Data persists in volume mount. Tar/copy the data directory. |

---

## 5. Directory Structure

```
~/brain-inbox/
├── projects/            # Project docs (markdown, text)
├── claude/              # Claude AI JSON (individual conversations)
├── grok/                # Grok exports
├── maps/                # Google Maps saved lists (CSV)
├── other/               # Anything else
├── classified/
│   ├── deep/            # Triage result: full extraction
│   ├── light/           # Triage result: summary only
│   └── skip/            # Triage result: no processing
├── processed/           # Successfully ingested files
└── failed/              # Files that errored (+ .error sidecars)

~/second-brain-data/     # ArcadeDB data volume (Docker mount)
```

---

## 6. Docker Commands

```bash
# Start ArcadeDB (first time)
docker-compose up -d

# Start (after stop)
docker start <YOUR_CONTAINER_NAME>

# Stop
docker stop <YOUR_CONTAINER_NAME>

# Restart
docker restart <YOUR_CONTAINER_NAME>

# View logs
docker logs <YOUR_CONTAINER_NAME> --tail 50

# Shell access
docker exec -it <YOUR_CONTAINER_NAME> sh

# Check MCP config
docker exec <YOUR_CONTAINER_NAME> sh -c "cat /home/arcadedb/config/mcp-config.json"

# Backup data directory
tar -czf second-brain-backup-$(date +%Y%m%d).tar.gz ~/second-brain-data/
```

---

## 7. Your Graph Stats

Fill in after your build is complete:

| Metric | Count |
|---|---|
| Concepts | |
| Decisions | |
| Artifacts | |
| Projects | |
| Persons | |
| Total nodes | |
| Total edges | |
| Embeddings | |
| Data sources ingested | |
