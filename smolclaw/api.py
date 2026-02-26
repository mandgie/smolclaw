"""REST API + dashboard serving — control plane for smolclaw."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from .gateway import Gateway


def create_app(gateway: Gateway) -> FastAPI:
    app = FastAPI(title="smolclaw", version="0.1.0")

    # --- Agent endpoints ---

    @app.get("/api/agents")
    async def list_agents():
        agents = []
        for name, agent in gateway.agents.items():
            channels = list(agent.info.config.channels.keys())
            agents.append({
                "name": name,
                "model": agent.model,
                "connected": agent.is_connected,
                "channels": channels,
                "skills": len(agent.info.skills),
                "memory": agent.memory.stats() if hasattr(agent, "memory") else None,
            })
        return {"agents": agents}

    @app.get("/api/agents/{name}")
    async def get_agent(name: str):
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
            "memory": agent.memory.stats() if hasattr(agent, "memory") else None,
            "context_files": list(agent.info.context_files.keys()),
        }

    @app.post("/api/agents/{name}/send")
    async def send_message(name: str, body: dict):
        text = body.get("text", "")
        if not text:
            raise HTTPException(400, "Missing 'text' field")

        try:
            response = await gateway.send(name, text)
            return {"response": response}
        except Exception as e:
            raise HTTPException(500, str(e))

    @app.post("/api/agents/{name}/new-session")
    async def new_session(name: str):
        agent = gateway.router.get_agent(name)
        if not agent:
            raise HTTPException(404, f"Agent '{name}' not found")
        await agent.new_session()
        return {"status": "ok"}

    # --- Cron endpoints ---

    @app.get("/api/cron/jobs")
    async def list_jobs():
        if gateway.scheduler:
            return {"jobs": gateway.scheduler.list_jobs()}
        return {"jobs": []}

    @app.post("/api/cron/jobs")
    async def add_job(body: dict):
        if not gateway.scheduler:
            raise HTTPException(500, "Scheduler not running")
        job = gateway.scheduler.add_job(body)
        return {"job": job.to_dict()}

    @app.delete("/api/cron/jobs/{job_id}")
    async def remove_job(job_id: str):
        if not gateway.scheduler:
            raise HTTPException(500, "Scheduler not running")
        removed = gateway.scheduler.remove_job(job_id)
        if not removed:
            raise HTTPException(404, f"Job '{job_id}' not found")
        return {"status": "removed"}

    # --- Health ---

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "agents": len(gateway.agents),
            "channels": len(gateway.channels),
            "jobs": len(gateway.scheduler.jobs) if gateway.scheduler else 0,
        }

    # --- Dashboard ---

    dashboard_dir = Path(__file__).parent / "dashboard"

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        index = dashboard_dir / "index.html"
        if index.exists():
            return index.read_text()
        return "<html><body><h1>smolclaw</h1><p>Dashboard not found.</p></body></html>"

    return app
