# Second Brain

A persistent personal knowledge graph that serves as the single source of truth across all your tools, agents, and workflows. Built on ArcadeDB with an open MCP interface, any framework — current or future — can read and write to it. Conversations, documents, decisions, maps, and research are indexed into one queryable brain that outlives whatever tools you happen to be using today. New knowledge enters by dropping a file into a folder.

## Architecture

```
Files dropped into ~/brain-inbox/
        |
        v
  Harvester (triage + extract)
        |  ArcadeDB MCP
        v
  ArcadeDB (graph + document + vector + full-text)
        |  ArcadeDB MCP
        v
  Any MCP-compatible agent or tool
```

## What It Does

- **Indexes everything** — conversations, documents, decisions, maps, research notes — into a queryable knowledge graph
- **5 node types:** Concept, Decision, Artifact, Person, Project
- **6 edge types:** RELATES_TO, MENTIONS, LED_TO, PART_OF, DERIVED_FROM, CONTRADICTS
- **Full-text search** via Lucene indexes on all major fields
- **Graph traversal** — find connections between any two pieces of knowledge
- **Vector similarity** — find semantically related nodes using embeddings
- **Decision tracking** — captures the *why* behind every choice, not just the *what*

## Quick Start

1. **Clone the repo**

   ```bash
   git clone https://github.com/your-username/second-brain.git
   cd second-brain
   ```

2. **Copy `.env.example` to `.env` and configure**

   ```bash
   cp .env.example .env
   # Edit .env with your ArcadeDB password and embedding API key
   ```

3. **Start ArcadeDB**

   ```bash
   docker-compose up -d
   ```

4. **Create the database and run the schema**

   Open ArcadeDB Studio at http://localhost:2480, create a database called `secondbrain`, then execute `schema/second-brain-schema.sql` in the Studio console.

5. **Create the inbox directory structure**

   ```bash
   mkdir -p ~/brain-inbox/{projects,claude,grok,maps,other}
   mkdir -p ~/brain-inbox/classified/{deep,light,skip}
   mkdir -p ~/brain-inbox/{processed,failed}
   ```

6. **Drop files into `~/brain-inbox/` and run the processing scripts**

   ```bash
   # Split a Claude export into individual conversations
   python scripts/split_claude.py conversations.json ~/brain-inbox/claude/

   # Triage conversations (classify as DEEP/LIGHT/SKIP)
   python scripts/triage_claude.py

   # Write extractions to the graph
   python scripts/graph_writer.py extractions/my-extraction.json
   ```

## Embedding Options

| Provider | Type | Cost | Dimensions | Notes |
|---|---|---|---|---|
| Ollama (nomic-embed-text) | Local | Free | 768 | Requires Ollama installed. Slower on CPU. |
| OpenRouter (Qwen3 Embedding 8B) | API | ~$0.01/M tokens | 1024 | Fast, no local GPU needed. |
| OpenAI (text-embedding-3-small) | API | $0.02/M tokens | 1536 | Highest quality, higher cost. |
| Custom | Any OpenAI-compatible endpoint | Varies | Varies | Set endpoint URL and model in `.env`. |

Embeddings are optional. The graph works without them — full-text search and graph traversal cover most queries. Embeddings add vector similarity ("find things like this"). If an embedding API call fails, the node is created with a `needs_embedding` flag and processing continues.

## Agent Integration

The Second Brain works with **any MCP-compatible agent framework**. ArcadeDB exposes its MCP server at `/api/v1/mcp` with tools for `query`, `execute_command`, `get_schema`, `list_databases`, and `server_status`.

### Agent Zero Example

The `agent-zero/` directory contains example configuration files:

- **`behaviour.md.example`** — Drop this into your agent's `memory/default/` directory (renamed to `behaviour.md`). It instructs the agent to automatically query the brain when answering knowledge questions.
- **`knowledge-file.md.example`** — Reference document with query patterns and graph statistics. Place in the agent's `knowledge/` directory.

### MCP Configuration

Any agent that supports MCP can connect using:

```json
{
  "mcpServers": {
    "arcadedb": {
      "url": "http://localhost:2480/api/v1/mcp",
      "type": "streaming-http",
      "headers": {
        "Authorization": "Basic <base64-encoded-credentials>"
      }
    }
  }
}
```

If your agent runs inside Docker, use `http://host.docker.internal:2480/api/v1/mcp` instead.

## Project Structure

```
second-brain/
├── README.md
├── docker-compose.yml              # ArcadeDB with MCP enabled
├── mcp-config.json                 # MCP server permissions
├── .env.example                    # Environment variables template
├── schema/
│   └── second-brain-schema.sql     # Vertex types, edge types, indexes
├── scripts/
│   ├── graph_writer.py             # Write extraction JSON to ArcadeDB via MCP
│   ├── split_claude.py             # Split Claude export into individual conversations
│   ├── triage_claude.py            # Classify conversations as DEEP/LIGHT/SKIP
│   ├── extract_claude_light.py     # Create summary Artifacts for LIGHT conversations
│   ├── embedding_backfill.py       # Generate embeddings for all nodes
│   └── process_maps.py             # Process Google Maps CSV exports
├── agent-zero/
│   ├── behaviour.md.example        # Agent system prompt integration
│   └── knowledge-file.md.example   # Query patterns reference
├── skills/
│   ├── triage/SKILL.md             # Classify incoming content
│   ├── extract/SKILL.md            # Entity extraction and graph writing
│   └── synthesize/SKILL.md         # Query interface for daily use
└── docs/
    ├── build-guide.md              # Step-by-step build process
    └── operations-template.md      # Fill-in template for your deployment
```

## Scripts

| Script | Purpose |
|---|---|
| `graph_writer.py` | Core graph writer. Reads extraction JSON, creates nodes and edges in ArcadeDB via MCP. Handles dedup by content hash and node name. |
| `split_claude.py` | Splits a Claude AI JSON export (array of conversations) into individual files for processing. |
| `triage_claude.py` | Classifies Claude conversations as DEEP (full extraction), LIGHT (summary only), or SKIP (no value). Moves files to classified directories. |
| `extract_claude_light.py` | Creates one Artifact node per LIGHT conversation with summary and project cross-references. |
| `embedding_backfill.py` | Generates vector embeddings for all nodes missing them. Supports OpenRouter, Ollama, or any OpenAI-compatible endpoint. |
| `process_maps.py` | Processes Google Maps saved-place CSV exports into Artifact nodes with location data. |

## Documentation

- **[Build Guide](docs/build-guide.md)** — Detailed walkthrough of the build process, schema rationale, architectural decisions, and known issues.
- **[Operations Template](docs/operations-template.md)** — Fill-in template for your deployment: credentials, query reference, maintenance schedule.

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
