# pattern: Imperative Shell
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from pipeline.config import settings
from pipeline.registry_api.db import init_db
from pipeline.registry_api.events import manager
from pipeline.registry_api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.

    On startup: Initialize the database schema.
    On shutdown: Nothing needed (connections are per-request).
    """
    init_db(settings.db_path)
    yield


app = FastAPI(title="QA Registry", lifespan=lifespan)
app.include_router(router)


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
    finally:
        manager.disconnect(websocket)


def run():
    """
    Entrypoint for the registry-api script.

    Starts the FastAPI application using uvicorn.
    """
    import uvicorn

    uvicorn.run("pipeline.registry_api.main:app", host="0.0.0.0", port=8000)
