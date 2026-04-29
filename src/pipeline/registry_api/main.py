# pattern: Imperative Shell
import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

from pipeline.config import settings
from pipeline.lexicons import load_all_lexicons
from pipeline.registry_api.db import DbDep, get_token_by_hash, init_db
from pipeline.registry_api.events import manager
from pipeline.registry_api.routes import public_router, protected_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
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
async def websocket_events(
    websocket: WebSocket,
    db: DbDep,
    token: str | None = Query(default=None),
) -> None:
    """
    One-way broadcast channel for delivery lifecycle events.

    Requires authentication via ?token= query parameter.
    Unauthenticated or invalid token connections are rejected with close code 1008
    (Policy Violation).

    Clients connect and receive JSON event broadcasts. The receive loop
    exists only to detect disconnection — clients don't send messages.
    """
    # Validate token before accepting the connection
    if token is None:
        await websocket.close(code=1008, reason="Missing authentication token")
        return

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    token_row = get_token_by_hash(db, token_hash)

    if token_row is None or token_row.get("revoked_at") is not None:
        await websocket.close(code=1008, reason="Invalid or revoked token")
        return

    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)


def run() -> None:
    """
    Entrypoint for the registry-api script.

    Starts the FastAPI application using uvicorn.
    """
    import uvicorn

    uvicorn.run("pipeline.registry_api.main:app", host=settings.api_host, port=settings.api_port)
