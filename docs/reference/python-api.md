# Python API Reference

smolclaw exports all core classes from the top-level package:

```python
from smolclaw import Agent, Gateway, Router, Memory, Scheduler
from smolclaw import AgentConfig, AgentInfo, GatewayConfig, MemoryConfig
from smolclaw import InboundMessage, OutboundMessage, Job
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
        - list_facts
        - delete_fact
        - add_chunk
        - search_chunks
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

## Configuration Models

::: smolclaw.config.AgentConfig

::: smolclaw.config.MemoryConfig

::: smolclaw.config.GatewayConfig

::: smolclaw.config.AgentInfo

## Message Types

::: smolclaw.router.InboundMessage

::: smolclaw.router.OutboundMessage

## Channel Base Class

::: smolclaw.channel.Channel
    options:
      members:
        - start
        - stop
        - send
