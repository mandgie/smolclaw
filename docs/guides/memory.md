# Memory

smolclaw includes a built-in persistent memory system backed by SQLite. Each agent gets its own namespace in a shared database, with optional cross-agent search.

## Configuration

Enable memory in `agent.yaml`:

```yaml
memory:
  enabled: true
  cross_agent: false  # Set to true to search other agents' memory
```

The database lives at `~/.smolclaw/shared/memory.db`.

## How It Works

Memory has two storage types:

### Facts

Structured knowledge — things the agent should remember.

| Field | Description |
|---|---|
| `content` | The fact text |
| `category` | Grouping label (default: `"general"`) |
| `source` | Where it came from (default: `"manual"`) |

### Chunks

Conversation history — user/assistant message pairs, automatically saved after each interaction.

| Field | Description |
|---|---|
| `user_text` | What the user said |
| `assistant_text` | What the agent replied |
| `session_id` | Which session it belongs to |

## Search Tiers

Memory supports three search tiers, using the best available automatically:

| Tier | Method | Requires | Description |
|---|---|---|---|
| 1 | **Vector search** | `sqlite-vec` + `embed_fn` | Semantic similarity via embeddings |
| 2 | **FTS5** | Built-in | BM25-ranked full-text search |
| 3 | **LIKE** | Built-in | Basic SQL pattern matching (fallback) |

### Hybrid Search

When vector search is available, **hybrid search** combines vector + FTS5 results using [Reciprocal Rank Fusion (RRF)](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf). This gives the best of both worlds — semantic understanding from vectors and keyword precision from FTS5.

### Enabling Vector Search

Install the optional `sqlite-vec` dependency:

```bash
pip install smolclaw[memory]
```

Then provide an embedding function when creating the Memory instance. The gateway does this automatically when `sqlite-vec` is installed.

## Using Memory in Code

```python
from smolclaw import Memory

mem = Memory(db_path=Path("memory.db"), agent="tars")

# Add a fact
fact_id = mem.add_fact("Magnus prefers concise responses", category="preferences")

# Search facts (uses best available method: FTS5 > LIKE)
results = mem.search_facts("preferences", limit=5)

# Vector search (requires sqlite-vec + embed_fn)
results = mem.vector_search_facts("what does the user prefer?", limit=5)

# Hybrid search (combines vector + FTS5 via RRF)
results = mem.hybrid_search_facts("user preferences", limit=5)

# Search across agents
results = mem.search_facts("calendar", cross_agent=True)

# Store a conversation chunk
mem.add_chunk(user_text="What's the weather?", assistant_text="Sunny, 22°C")

# List all facts
facts = mem.list_facts(limit=50, category="preferences")

# Get stats
stats = mem.stats()  # {"facts": 42, "chunks": 156, "vec_facts": 42, ...}

# Delete a specific fact
mem.delete_fact(fact_id)

# Clear all memory for this agent
mem.clear()  # {"facts_deleted": 42, "chunks_deleted": 156}
```

## REST API

Manage memory through the API:

```bash
# List facts
curl http://localhost:7890/api/agents/tars/memory/facts

# List facts by category
curl "http://localhost:7890/api/agents/tars/memory/facts?category=preferences"

# Search memory (auto mode — uses FTS5 > LIKE)
curl "http://localhost:7890/api/agents/tars/memory/search?q=preferences"

# Vector search
curl "http://localhost:7890/api/agents/tars/memory/search?q=preferences&mode=vector"

# Hybrid search (vector + FTS5 combined)
curl "http://localhost:7890/api/agents/tars/memory/search?q=preferences&mode=hybrid"

# Cross-agent search
curl "http://localhost:7890/api/agents/tars/memory/search?q=calendar&cross_agent=true"

# Add a fact
curl -X POST http://localhost:7890/api/agents/tars/memory/facts \
  -H "Content-Type: application/json" \
  -d '{"content": "User prefers metric units", "category": "preference"}'

# Get memory stats
curl http://localhost:7890/api/agents/tars/memory/stats

# Delete a fact
curl -X DELETE http://localhost:7890/api/agents/tars/memory/facts/42

# Clear all memory
curl -X DELETE http://localhost:7890/api/agents/tars/memory
```

## CLI

```bash
# Memory statistics
smolclaw memory stats tars

# List stored facts
smolclaw memory list tars

# Search memory
smolclaw memory search tars "user preferences"

# Add a fact
smolclaw memory add tars "User prefers dark mode"

# View a single fact
smolclaw memory get tars 42

# Update a fact
smolclaw memory update tars 42 --content "User prefers light mode" -c preference

# Delete a fact
smolclaw memory delete tars 42
```

## Namespacing

All agents share one SQLite database, but each agent's data is scoped by an `agent` column. An agent named "tars" can only see its own facts and chunks by default.

With `cross_agent: true`, the agent can also search other agents' memory — useful for scenarios like a fitness coach agent accessing calendar data from a personal assistant agent.

## Technical Details

- **WAL mode** — SQLite Write-Ahead Logging for concurrent read access
- **5-second timeout** — prevents "database is locked" errors under load
- **FTS5 indexing** — automatic full-text search index on facts and chunks
- **sqlite-vec** — optional vector search with embedding support (`pip install smolclaw[memory]`)
- **RRF hybrid** — reciprocal rank fusion combines vector and FTS5 results for optimal retrieval
- **Agent isolation** — delete operations enforce agent boundaries (can't delete another agent's facts)
