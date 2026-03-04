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

Conversation history — user/assistant message pairs.

| Field | Description |
|---|---|
| `user_text` | What the user said |
| `assistant_text` | What the agent replied |
| `session_id` | Which session it belongs to |

## Using Memory in Code

```python
from smolclaw import Memory

mem = Memory(db_path=Path("memory.db"), agent="tars")

# Add a fact
fact_id = mem.add_fact("Magnus prefers concise responses", category="preferences")

# Search facts
results = mem.search_facts("preferences", limit=5)

# Search across agents
results = mem.search_facts("calendar", cross_agent=True)

# Store a conversation chunk
mem.add_chunk(user_text="What's the weather?", assistant_text="Sunny, 22°C")

# List all facts
facts = mem.list_facts(limit=50, category="preferences")

# Get stats
stats = mem.stats()  # {"facts": 42, "chunks": 156}

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

# Delete a fact
curl -X DELETE http://localhost:7890/api/agents/tars/memory/facts/42

# Clear all memory
curl -X DELETE http://localhost:7890/api/agents/tars/memory
```

## Namespacing

All agents share one SQLite database, but each agent's data is scoped by an `agent` column. An agent named "tars" can only see its own facts and chunks by default.

With `cross_agent: true`, the agent can also search other agents' memory — useful for scenarios like a fitness coach agent accessing calendar data from a personal assistant agent.

## Technical Details

- **WAL mode** — SQLite Write-Ahead Logging for concurrent read access
- **5-second timeout** — prevents "database is locked" errors under load
- **LIKE search** — current search uses SQL LIKE patterns (vector search with sqlite-vec is planned)
- **Agent isolation** — delete operations enforce agent boundaries (can't delete another agent's facts)
