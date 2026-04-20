# pattern: Imperative Shell
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from pipeline.config import settings
from pipeline.lexicons import load_all_lexicons
from pipeline.registry_api.db import init_db
from pipeline.registry_api.events import manager
from pipeline.registry_api.routes import public_router, protected_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.

    On startup: Initialize the database schema and load lexicons.
    On shutdown: Nothing needed (connections are per-request).
    """
    init_db(settings.db_path)
    app.state.lexicons = load_all_lexicons(settings.lexicons_dir)
    app.state.scan_roots = settings.scan_roots
    yield


app = FastAPI(title="QA Registry", lifespan=lifespan)
app.include_router(public_router)
app.include_router(protected_router)


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    One-way broadcast channel for delivery lifecycle events.

    Clients connect and receive JSON event broadcasts. The receive loop
    exists only to detect disconnection — clients don't send messages.
    """
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)


def run():
    """
    Entrypoint for the registry-api script.

    Starts the FastAPI application using uvicorn.
    """
    import uvicorn

    uvicorn.run("pipeline.registry_api.main:app", host=settings.api_host, port=settings.api_port)
