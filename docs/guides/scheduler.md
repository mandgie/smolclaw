# Scheduler

smolclaw includes a built-in cron scheduler for running recurring agent tasks. Scheduled jobs fire through the same message router as everything else — a cron job is just another message to your agent.

## How It Works

1. Jobs are defined with cron expressions (e.g., `0 8 * * 1-5` = weekdays at 8 AM)
2. The scheduler checks every 30 seconds for due jobs
3. When a job fires, it sends the prompt as an `InboundMessage` through the router
4. The agent processes it like any other message
5. Optionally, the response is delivered to a channel (e.g., Telegram)

## Adding Jobs

### Via CLI

```bash
# Inline prompt
smolclaw cron add \
  --agent tars \
  --schedule "0 8 * * 1-5" \
  --prompt "Give me a morning briefing: calendar, priority emails, weather."

# Prompt from file
smolclaw cron add \
  --agent tars \
  --schedule "0 8 * * 1-5" \
  --prompt prompts/morning-briefing.md

# With delivery to Telegram
smolclaw cron add \
  --agent tars \
  --schedule "0 8 * * 1-5" \
  --prompt "Morning briefing" \
  --delivery telegram \
  --chat-id 123456789

# Custom job ID
smolclaw cron add \
  --agent tars \
  --schedule "30 17 * * 5" \
  --prompt "Weekly review" \
  --id weekly-review
```

### Via API

```bash
curl -X POST http://localhost:7890/api/cron/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "tars",
    "schedule": "0 8 * * 1-5",
    "prompt": "Morning briefing",
    "enabled": true
  }'
```

## Listing Jobs

```bash
smolclaw cron list
```

Shows a table with job ID, agent, schedule, status, and next run time.

## Removing Jobs

```bash
smolclaw cron remove morning-briefing
```

## Enable / Disable Jobs

Pause a job without removing it:

```bash
smolclaw cron disable morning-briefing
smolclaw cron enable morning-briefing
```

Disabled jobs are skipped during scheduling but retain their configuration and history.

You can also enable/disable via the REST API:

```bash
curl -s -X POST localhost:7890/api/cron/jobs/morning-briefing/disable
curl -s -X POST localhost:7890/api/cron/jobs/morning-briefing/enable
```

## Manual Triggering

Run a job immediately for testing, without waiting for its schedule:

```bash
smolclaw cron run morning-briefing
```

This sends the job's prompt through the gateway API and delivers the response through the configured delivery channel (e.g., Telegram).

## Job Storage

Jobs are stored in `~/.smolclaw/shared/cron/jobs.json` with runtime state:

```json
[
  {
    "id": "morning-briefing",
    "agent": "tars",
    "schedule": "0 8 * * 1-5",
    "prompt": "Morning briefing",
    "enabled": true,
    "delivery": "telegram",
    "delivery_chat_id": "123456789",
    "session_mode": "new",
    "last_run": "2026-03-04T08:00:00",
    "next_run": "2026-03-05T08:00:00",
    "status": "ok",
    "failures": 0
  }
]
```

## Prompt Files

For longer prompts, create a markdown file in the agent's `prompts/` directory:

```
~/.smolclaw/agents/tars/prompts/morning-briefing.md
```

Reference it by filename in the cron command — smolclaw detects files automatically.

## Cron Expression Reference

| Expression | Meaning |
|---|---|
| `* * * * *` | Every minute |
| `0 * * * *` | Every hour |
| `0 8 * * *` | Daily at 8:00 AM |
| `0 8 * * 1-5` | Weekdays at 8:00 AM |
| `30 17 * * 5` | Fridays at 5:30 PM |
| `0 0 1 * *` | First of every month |

Format: `minute hour day-of-month month day-of-week`

## Error Handling

- Invalid cron expressions are rejected at creation time
- Failed jobs increment a `failures` counter and set `status: "error"`
- The scheduler continues running other jobs even if one fails
- Disabled jobs (`enabled: false`) are skipped during scheduling
