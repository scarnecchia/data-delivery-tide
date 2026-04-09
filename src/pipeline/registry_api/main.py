from contextlib import asynccontextmanager

from fastapi import FastAPI

from pipeline.config import settings
from pipeline.registry_api.db import init_db
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


def run():
    """
    Entrypoint for the registry-api script.

    Starts the FastAPI application using uvicorn.
    """
    import uvicorn

    uvicorn.run("pipeline.registry_api.main:app", host="0.0.0.0", port=8000)
