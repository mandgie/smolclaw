"""REST API + dashboard serving — control plane for smolclaw."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

__all__ = ["create_app"]

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .gateway import Gateway


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
