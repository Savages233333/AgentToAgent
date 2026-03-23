from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from agent_to_agent.api import router as api_router
from agent_to_agent.heartbeatmonitor.heartbeatMonitor import HeartbeatMonitor
from agent_to_agent.middleware import register_middlewares
from agent_to_agent.models import get_db


DEPLOYMENT_MODE = "single-instance in-memory"


@asynccontextmanager
async def lifespan(app: FastAPI):
    monitor = HeartbeatMonitor(db_session_func=get_db)
    app.state.heartbeat_monitor = monitor
    app.state.deployment_mode = DEPLOYMENT_MODE
    monitor.start()
    print(
        "[AgentToAgent] Deployment mode: single-instance in-memory. "
        "Runtime agents are stored in-process and are not shared across replicas."
    )
    try:
        yield
    finally:
        monitor.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentToAgent",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_middlewares(app)
    app.include_router(api_router)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "deployment_mode": DEPLOYMENT_MODE,
        }

    return app


app = create_app()


def main() -> None:
    uvicorn.run("agent_to_agent.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
