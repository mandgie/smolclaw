# Hooks

Hooks are pre-route and post-route middleware that intercept messages flowing through the router. Use them to log, filter, modify, redirect, or transform messages without touching agent code.

## Concepts

Every message in smolclaw follows this path:

```
InboundMessage → Pre-hooks → Agent → Post-hooks → OutboundMessage
```

**Pre-route hooks** run before the agent processes the message. They can:

- **Pass through** — return `None` to leave the message unchanged
- **Modify** — return a new `InboundMessage` (e.g., rewrite text, change target agent)
- **Short-circuit** — return an `OutboundMessage` to skip the agent entirely

**Post-route hooks** run after the agent responds. They can:

- **Pass through** — return `None` to leave the response unchanged
- **Transform** — return a new `OutboundMessage` (e.g., append a footer, redact content)

## Using Hooks

### Register hooks programmatically

```python
from smolclaw import HookRegistry, HookContext, InboundMessage, OutboundMessage

hooks = HookRegistry()

# Pre-route: log all incoming messages
async def logger(msg: InboundMessage, ctx: HookContext):
    print(f"[{ctx.agent_name}] {msg.text[:50]}")
    return None  # pass through

hooks.add_pre_hook("logger", logger)

# Post-route: add a footer to all responses
async def footer(msg: InboundMessage, resp: OutboundMessage, ctx: HookContext):
    return OutboundMessage(
        agent=resp.agent,
        text=resp.text + "\n\n---\n_Powered by smolclaw_",
        source=resp.source,
        chat_id=resp.chat_id,
    )

hooks.add_post_hook("footer", footer)
```

### Pass hooks to the Router

```python
from smolclaw import Router

router = Router(hooks=hooks)
```

## Examples

### Rate limiter

Block excessive messages from a single source:

```python
from collections import defaultdict
import time

rate_counts: dict[str, list[float]] = defaultdict(list)

async def rate_limit(msg, ctx):
    key = f"{ctx.agent_name}:{msg.chat_id}"
    now = time.time()
    # Keep only timestamps from the last 60 seconds
    rate_counts[key] = [t for t in rate_counts[key] if now - t < 60]
    if len(rate_counts[key]) >= 10:
        return OutboundMessage(
            agent=msg.agent, text="Too many messages. Please wait.",
            source=msg.source, chat_id=msg.chat_id,
        )
    rate_counts[key].append(now)
    return None

hooks.add_pre_hook("rate-limiter", rate_limit)
```

### Content filter

Redact sensitive patterns from responses:

```python
import re

async def redact_secrets(msg, resp, ctx):
    cleaned = re.sub(r"sk-[a-zA-Z0-9]{20,}", "[REDACTED]", resp.text)
    if cleaned != resp.text:
        return OutboundMessage(
            agent=resp.agent, text=cleaned,
            source=resp.source, chat_id=resp.chat_id,
        )
    return None

hooks.add_post_hook("redact-secrets", redact_secrets)
```

### Agent redirect

Route certain messages to a different agent:

```python
async def redirect_code(msg, ctx):
    if "review this code" in msg.text.lower():
        return InboundMessage(
            agent="code-reviewer",  # redirect to specialized agent
            text=msg.text,
            source=msg.source,
            chat_id=msg.chat_id,
        )
    return None

hooks.add_pre_hook("code-redirect", redirect_code)
```

## Hook Context

Every hook receives a `HookContext` with:

| Field | Type | Description |
|---|---|---|
| `agent_name` | str | Target agent name |
| `source` | str | Message source (telegram, cli, api, cron) |
| `metadata` | dict | Arbitrary key-value store for sharing state between hooks |

The `metadata` dict persists across all hooks in a single message's lifecycle, allowing hooks to communicate:

```python
async def set_flag(msg, ctx):
    ctx.metadata["is_priority"] = "urgent" in msg.text.lower()
    return None

async def log_priority(msg, resp, ctx):
    if ctx.metadata.get("is_priority"):
        print(f"PRIORITY response: {resp.text[:100]}")
    return None
```

## Managing Hooks

```python
# Remove a hook by name
hooks.remove_hook("logger")

# Clear all hooks
hooks.clear()

# List registered hooks
print(hooks.pre_hook_names)   # ["rate-limiter", "code-redirect"]
print(hooks.post_hook_names)  # ["footer", "redact-secrets"]

# Summary stats
print(hooks.stats)
# {"pre_route": [...], "post_route": [...], "total": 4}
```

## REST API

Check registered hooks via the API:

```bash
curl http://localhost:7890/api/hooks
```

```json
{
  "pre_route": ["rate-limiter", "code-redirect"],
  "post_route": ["footer", "redact-secrets"],
  "total": 4
}
```

## Error Handling

Hooks are error-isolated — if a hook raises an exception, it's logged and the chain continues. A failing hook never breaks message delivery.
