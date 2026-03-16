# Python API Reference

smolclaw exports all core classes from the top-level package:

```python
from smolclaw import Agent, Gateway, Router, Memory, Scheduler
from smolclaw import AgentConfig, AgentInfo, GatewayConfig, MemoryConfig
from smolclaw import InboundMessage, OutboundMessage, Job
from smolclaw import HookRegistry, HookContext, PreRouteHook, PostRouteHook
from smolclaw import TelegramChannel, WebhookChannel
from smolclaw import create_channel, register_channel, list_channel_types
from smolclaw import FileWatcher
from smolclaw import TracingConfig, configure_tracing, span, TRACING_AVAILABLE
```

## Core Classes

::: smolclaw.gateway.Gateway
    options:
      members:
        - start
        - stop
        - send

::: smolclaw.agent.Agent
    options:
      members:
        - __init__
        - build_system_prompt
        - connect
        - send
        - new_session
        - shutdown

::: smolclaw.router.Router
    options:
      members:
        - register_agent
        - on_response
        - route
        - get_agent

::: smolclaw.memory.Memory
    options:
      members:
        - __init__
        - add_fact
        - search_facts
        - vector_search_facts
        - hybrid_search_facts
        - list_facts
        - delete_fact
        - add_chunk
        - search_chunks
        - vector_search_chunks
        - hybrid_search_chunks
        - clear
        - stats

::: smolclaw.scheduler.Scheduler
    options:
      members:
        - __init__
        - load_jobs
        - save_jobs
        - start
        - stop
        - add_job
        - remove_job
        - list_jobs

## Hooks

::: smolclaw.hooks.HookRegistry
    options:
      members:
        - add_pre_hook
        - add_post_hook
        - remove_hook
        - clear
        - run_pre_hooks
        - run_post_hooks
        - pre_hook_names
        - post_hook_names
        - stats

::: smolclaw.hooks.HookContext

## Channel System

::: smolclaw.channel.Channel
    options:
      members:
        - start
        - stop
        - send

::: smolclaw.channel.TelegramChannel

::: smolclaw.channel.WebhookChannel

### Channel Registry Functions

```python
from smolclaw import register_channel, list_channel_types, create_channel

# Register a custom channel type
register_channel("discord", DiscordChannel)

# List all available channel types (built-in + custom + entry points)
types = list_channel_types()
# {'telegram': TelegramChannel, 'webhook': WebhookChannel, 'discord': DiscordChannel}

# Create a channel instance by type name
channel = create_channel("telegram", agent_name="tars", config=cfg, router=router)
```

## Configuration Models

::: smolclaw.config.AgentConfig

::: smolclaw.config.MemoryConfig

::: smolclaw.config.GatewayConfig

::: smolclaw.config.AgentInfo

## Message Types

::: smolclaw.router.InboundMessage

::: smolclaw.router.OutboundMessage

## Tracing

::: smolclaw.tracing.TracingConfig

```python
from smolclaw import configure_tracing, span, TRACING_AVAILABLE

# Check if OpenTelemetry is installed
if TRACING_AVAILABLE:
    configure_tracing(TracingConfig(enabled=True, endpoint="http://localhost:4318"))

# Use the @span decorator on any async function
@span("my_operation")
async def do_work():
    ...
```

## File Watcher

::: smolclaw.watcher.FileWatcher
