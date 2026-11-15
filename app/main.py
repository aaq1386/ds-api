import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.logging_config import setup_logging
from app.api import register_error_handlers, health, conversations, chat, system

logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.3.0",
    description="Stable API for DeepSeek Chat",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)
app.include_router(health.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(system.router)


@app.get("/")
async def root():
    return {"app": settings.app_name, "version": "0.3.0", "docs": "/docs", "health": "/health"}
