"""REST API + dashboard serving — control plane for smolclaw."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

__all__ = ["create_app"]

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .agent import Agent
    from .gateway import Gateway

_SESSION_ID_RE = re.compile(r"^[a-f0-9\-]+$")


def _sessions_dir_for_agent(agent: Agent) -> Path:
    """Compute the Claude Code sessions directory for an agent.

    Claude Code stores sessions in ~/.claude/projects/{encoded_cwd}/
    where the cwd path has / and . replaced with -.
    """
    cwd = str(agent.info.path.resolve())
    encoded = cwd.replace("/", "-").replace(".", "-")
    return Path.home() / ".claude" / "projects" / encoded


def _extract_user_text(content: Any) -> str:
    """Extract readable text from a user message content field."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                # Skip tool_result blocks
        return " ".join(parts)
    return ""


def _extract_assistant_text(content: Any) -> str:
    """Extract readable text from an assistant message content field."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    name = block.get("name", "unknown")
                    parts.append(f"[Tool: {name}]")
        return "\n".join(parts)
    return ""


def _parse_session_meta(path: Path) -> dict[str, Any] | None:
    """Extract metadata from a session JSONL file without full parsing."""
    session_id = path.stem
    stat = path.stat()
    first_user_msg = None
    msg_count = 0
    first_ts = None
    last_ts = None

    with open(path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            entry_type = entry.get("type")
            if entry_type not in ("user", "assistant"):
                continue

            msg_count += 1
            ts = entry.get("timestamp")
            if ts and not first_ts:
                first_ts = ts
            if ts:
                last_ts = ts

            if entry_type == "user" and not first_user_msg:
                content = entry.get("message", {}).get("content", "")
                text = _extract_user_text(content)
                if text:
                    first_user_msg = text[:120]

    if msg_count == 0:
        return None

    return {
        "id": session_id,
        "messages": msg_count,
        "size_bytes": stat.st_size,
        "created": first_ts,
        "updated": last_ts,
        "preview": first_user_msg or "",
    }


def _parse_session_messages(path: Path) -> list[dict[str, Any]]:
    """Parse a session JSONL into a list of user/assistant messages."""
    messages = []

    with open(path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            entry_type = entry.get("type")

            if entry_type == "user":
                content = entry.get("message", {}).get("content", "")
                text = _extract_user_text(content)
                if text:
                    messages.append(
                        {
                            "role": "user",
                            "text": text,
                            "timestamp": entry.get("timestamp"),
                        }
                    )

            elif entry_type == "assistant":
                content = entry.get("message", {}).get("content", [])
                text = _extract_assistant_text(content)
                if text:
                    messages.append(
                        {
                            "role": "assistant",
                            "text": text,
                            "timestamp": entry.get("timestamp"),
                            "model": entry.get("message", {}).get("model"),
                        }
                    )

    return messages


# --- Request / Response Models ---


class SendMessageRequest(BaseModel):
    """Request body for sending a message to an agent."""

    text: str = Field(..., min_length=1, description="Message text to send to the agent")
    session_key: str | None = Field(None, description="Optional session key for context")


class SendMessageResponse(BaseModel):
    """Response from sending a message to an agent."""

    response: str
    cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    structured_output: Any = None
    num_turns: int | None = None
    duration_ms: int | None = None
    stop_reason: str | None = None


class AddJobRequest(BaseModel):
    """Request body for adding a scheduled job."""

    id: str = Field(..., description="Unique job identifier")
    agent: str = Field(..., description="Target agent name")
    schedule: str = Field(..., description="Cron expression (e.g. '0 8 * * 1-5')")
    prompt: str = Field("", description="Inline prompt text")
    prompt_file: str = Field("", description="Path to prompt file (relative to agent prompts dir)")
    enabled: bool = Field(True, description="Whether the job is active")
    delivery: str = Field("", description="Delivery channel type (e.g. 'telegram')")
    delivery_chat_id: str = Field("", description="Chat ID for delivery")
    session_mode: str = Field("isolated", description="Session mode: 'isolated' or 'shared'")


class ClearMemoryResponse(BaseModel):
    """Response from clearing an agent's memory."""

    facts_deleted: int
    chunks_deleted: int


class StatusResponse(BaseModel):
    """Generic status response."""

    status: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    agents: int
    channels: int
    jobs: int


def create_app(gateway: Gateway) -> FastAPI:
    """Create the FastAPI application with all smolclaw endpoints."""
    from . import __version__

    app = FastAPI(
        title="smolclaw",
        version=__version__,
        description="Lightweight multi-agent framework for personal AI assistants",
    )

    # --- Agent endpoints ---

    @app.get("/api/agents")
    async def list_agents() -> dict[str, Any]:
        """List all registered agents with their status and configuration."""
        agents = []
        for name, agent in gateway.agents.items():
            channels = list(agent.info.config.channels.keys())
            agents.append(
                {
                    "name": name,
                    "model": agent.model,
                    "connected": agent.is_connected,
                    "channels": channels,
                    "skills": len(agent.info.skills),
                    "memory": agent.memory.stats() if agent.memory else None,
                }
            )
        return {"agents": agents}

    @app.get("/api/agents/{name}")
    async def get_agent(name: str) -> dict[str, Any]:
        """Get detailed information about a specific agent."""
        agent = gateway.router.get_agent(name)
        if not agent:
            raise HTTPException(404, f"Agent '{name}' not found")

        return {
            "name": agent.name,
            "model": agent.model,
            "connected": agent.is_connected,
            "channels": list(agent.info.config.channels.keys()),
            "skills": len(agent.info.skills),
            "soul": agent.info.soul[:500] if agent.info.soul else "",
            "agents_md": agent.info.agents_md[:500] if agent.info.agents_md else "",
            "memory": agent.memory.stats() if agent.memory else None,
            "context_files": list(agent.info.context_files.keys()),
        }

    @app.post("/api/agents/{name}/send", response_model=SendMessageResponse)
    async def send_message(name: str, body: SendMessageRequest) -> dict[str, Any]:
        """Send a message to an agent and get the response."""
        try:
            response = await gateway.send(name, body.text)
            agent = gateway.router.get_agent(name)
            result: dict[str, Any] = {"response": response}
            if agent:
                result["cost_usd"] = agent.last_cost_usd
                result["usage"] = agent.last_usage
                result["structured_output"] = agent.last_structured_output
                result["num_turns"] = agent.last_num_turns
                result["duration_ms"] = agent.last_duration_ms
                result["stop_reason"] = agent.last_stop_reason
            return result
        except Exception as e:
            raise HTTPException(500, str(e))

    @app.post("/api/agents/{name}/new-session", response_model=StatusResponse)
    async def new_session(name: str) -> dict[str, str]:
        """Clear an agent's current session and start fresh."""
        agent = gateway.router.get_agent(name)
        if not agent:
            raise HTTPException(404, f"Agent '{name}' not found")
        await agent.new_session()
        return {"status": "ok"}

    # --- Session endpoints ---

    @app.get("/api/agents/{name}/sessions")
    async def list_sessions(name: str) -> dict[str, Any]:
        """List conversation sessions for an agent."""
        agent = gateway.router.get_agent(name)
        if not agent:
            raise HTTPException(404, f"Agent '{name}' not found")

        sdir = _sessions_dir_for_agent(agent)
        if not sdir.exists():
            return {"sessions": []}

        sessions = []
        for f in sorted(sdir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            meta = _parse_session_meta(f)
            if meta:
                sessions.append(meta)

        return {"sessions": sessions}

    @app.get("/api/agents/{name}/sessions/{session_id}")
    async def get_session(name: str, session_id: str) -> dict[str, Any]:
        """Read messages from a specific session."""
        if not _SESSION_ID_RE.match(session_id):
            raise HTTPException(400, "Invalid session ID format")

        agent = gateway.router.get_agent(name)
        if not agent:
            raise HTTPException(404, f"Agent '{name}' not found")

        sdir = _sessions_dir_for_agent(agent)
        session_file = sdir / f"{session_id}.jsonl"
        if not session_file.exists():
            raise HTTPException(404, f"Session '{session_id}' not found")

        messages = _parse_session_messages(session_file)
        return {"session_id": session_id, "messages": messages}

    # --- Memory endpoints ---

    @app.get("/api/agents/{name}/memory/facts")
    async def list_facts(
        name: str, limit: int = 100, category: str | None = None
    ) -> dict[str, Any]:
        """List facts stored in an agent's memory."""
        agent = gateway.router.get_agent(name)
        if not agent:
            raise HTTPException(404, f"Agent '{name}' not found")
        if not agent.memory:
            raise HTTPException(400, f"Agent '{name}' has no memory enabled")
        return {"facts": agent.memory.list_facts(limit=limit, category=category)}

    @app.delete("/api/agents/{name}/memory/facts/{fact_id}")
    async def delete_fact(name: str, fact_id: int) -> dict[str, str]:
        """Delete a specific fact from an agent's memory."""
        agent = gateway.router.get_agent(name)
        if not agent:
            raise HTTPException(404, f"Agent '{name}' not found")
        if not agent.memory:
            raise HTTPException(400, f"Agent '{name}' has no memory enabled")
        deleted = agent.memory.delete_fact(fact_id)
        if not deleted:
            raise HTTPException(404, f"Fact {fact_id} not found")
        return {"status": "deleted"}

    @app.delete("/api/agents/{name}/memory", response_model=ClearMemoryResponse)
    async def clear_memory(name: str) -> dict[str, int]:
        """Clear all facts and chunks from an agent's memory."""
        agent = gateway.router.get_agent(name)
        if not agent:
            raise HTTPException(404, f"Agent '{name}' not found")
        if not agent.memory:
            raise HTTPException(400, f"Agent '{name}' has no memory enabled")
        result = agent.memory.clear()
        return result

    # --- Cron endpoints ---

    @app.get("/api/cron/jobs")
    async def list_jobs() -> dict[str, Any]:
        """List all scheduled cron jobs."""
        if gateway.scheduler:
            return {"jobs": gateway.scheduler.list_jobs()}
        return {"jobs": []}

    @app.post("/api/cron/jobs")
    async def add_job(body: AddJobRequest) -> dict[str, Any]:
        """Add a new scheduled cron job."""
        if not gateway.scheduler:
            raise HTTPException(500, "Scheduler not running")
        job = gateway.scheduler.add_job(body.model_dump())
        return {"job": job.to_dict()}

    @app.delete("/api/cron/jobs/{job_id}", response_model=StatusResponse)
    async def remove_job(job_id: str) -> dict[str, str]:
        """Remove a scheduled cron job by ID."""
        if not gateway.scheduler:
            raise HTTPException(500, "Scheduler not running")
        removed = gateway.scheduler.remove_job(job_id)
        if not removed:
            raise HTTPException(404, f"Job '{job_id}' not found")
        return {"status": "removed"}

    # --- Health ---

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> dict[str, Any]:
        """Health check endpoint with system status."""
        from . import __version__

        return {
            "status": "ok",
            "version": __version__,
            "agents": len(gateway.agents),
            "channels": len(gateway.channels),
            "jobs": len(gateway.scheduler.jobs) if gateway.scheduler else 0,
        }

    # --- Dashboard ---

    dashboard_dir = Path(__file__).parent / "dashboard"

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> str:
        """Serve the smolclaw dashboard."""
        index = dashboard_dir / "index.html"
        if index.exists():
            return index.read_text()
        return "<html><body><h1>smolclaw</h1><p>Dashboard not found.</p></body></html>"

    return app
