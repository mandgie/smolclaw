# REST API Reference

The gateway runs a FastAPI server at `http://localhost:7890` by default. Interactive docs are available at `/docs` (Swagger UI).

## Agents

### List Agents

```
GET /api/agents
```

**Response:**
```json
{
  "agents": [
    {
      "name": "tars",
      "model": "claude-opus-4-6",
      "connected": true,
      "channels": ["telegram"],
      "skills": ["remindctl", "weather"],
      "memory": {"facts": 42, "chunks": 156}
    }
  ]
}
```

### Get Agent Details

```
GET /api/agents/{name}
```

**Response:**
```json
{
  "name": "tars",
  "model": "claude-opus-4-6",
  "connected": true,
  "channels": ["telegram"],
  "skills": ["remindctl"],
  "soul": "# TARS\nYou are TARS...",
  "agents_md": "# Operational Rules...",
  "memory": {"facts": 42, "chunks": 156},
  "context_files": ["COMPANY.md"]
}
```

### Send Message

```
POST /api/agents/{name}/send
```

**Request:**
```json
{
  "text": "What's on my calendar today?",
  "session_key": "optional-session-id"
}
```

**Response:**
```json
{
  "response": "You have 3 meetings today..."
}
```

### New Session

```
POST /api/agents/{name}/new-session
```

Clears the agent's current session for a fresh start.

**Response:**
```json
{
  "status": "ok"
}
```

## Memory

### List Facts

```
GET /api/agents/{name}/memory/facts
```

**Query Parameters:**

| Parameter | Default | Description |
|---|---|---|
| `limit` | `100` | Maximum facts to return |
| `category` | none | Filter by category |

**Response:**
```json
{
  "facts": [
    {
      "id": 1,
      "agent": "tars",
      "content": "Magnus prefers concise responses",
      "category": "preferences",
      "source": "manual",
      "created_at": "2026-03-04T10:30:00"
    }
  ]
}
```

### Delete Fact

```
DELETE /api/agents/{name}/memory/facts/{fact_id}
```

**Response:**
```json
{
  "status": "deleted"
}
```

### Clear Memory

```
DELETE /api/agents/{name}/memory
```

Deletes all facts and chunks for the agent.

**Response:**
```json
{
  "facts_deleted": 42,
  "chunks_deleted": 156
}
```

## Cron Jobs

### List Jobs

```
GET /api/cron/jobs
```

**Response:**
```json
{
  "jobs": [
    {
      "id": "morning-briefing",
      "agent": "tars",
      "schedule": "0 8 * * 1-5",
      "enabled": true,
      "delivery": "telegram",
      "delivery_chat_id": "123456789",
      "last_run": "2026-03-04T08:00:00",
      "next_run": "2026-03-05T08:00:00",
      "status": "ok",
      "failures": 0
    }
  ]
}
```

### Add Job

```
POST /api/cron/jobs
```

**Request:**
```json
{
  "agent": "tars",
  "schedule": "0 8 * * 1-5",
  "prompt": "Morning briefing",
  "enabled": true,
  "delivery": "telegram",
  "delivery_chat_id": "123456789"
}
```

### Remove Job

```
DELETE /api/cron/jobs/{job_id}
```

**Response:**
```json
{
  "status": "removed"
}
```

## Health

### Health Check

```
GET /api/health
```

**Response:**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "agents": 2,
  "channels": 1,
  "jobs": 3
}
```

## Dashboard

```
GET /
```

Serves a built-in dark-mode dashboard with agent status, configuration, and messaging.

## Error Responses

All error responses follow this format:

```json
{
  "detail": "Error description"
}
```

| Status | Meaning |
|---|---|
| `400` | Bad request (missing agent, disabled memory) |
| `404` | Agent or resource not found |
| `422` | Validation error (invalid request body) |
| `500` | Internal server error |
