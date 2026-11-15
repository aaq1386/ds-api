from fastapi import APIRouter
from app.config import settings

router = APIRouter()


@router.get("/health")
async def health():
    return {"ok": True, "app": settings.app_name, "version": "0.2.0"}
