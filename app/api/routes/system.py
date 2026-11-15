import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.auth import AuthManager
from app.security.secrets import redact

router = APIRouter(prefix="/api/system", tags=["system"])
logger = logging.getLogger("system")


class ReloadResponse(BaseModel):
    ok: bool
    token_len: int
    has_cf_clearance: bool
    user_agent_len: int


@router.post("/reload-token", response_model=ReloadResponse)
async def reload_token():
    try:
        auth = AuthManager()
        cookies = auth.load_cookies()
        token = cookies.get("ds_session_id", "")
        if not token:
            raise HTTPException(400, "No ds_session_id in config/cookies.json")
        ua = auth.load_user_agent()
        return ReloadResponse(
            ok=True, token_len=len(token),
            has_cf_clearance="cf_clearance" in cookies,
            user_agent_len=len(ua),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, redact(str(e)))


class ModelInfo(BaseModel):
    id: str
    name: str
    description: str


@router.get("/models", response_model=list[ModelInfo])
async def list_models():
    return [
        ModelInfo(id="default", name="Default", description="DeepSeek V3"),
        ModelInfo(id="reasoner", name="Reasoner", description="DeepSeek R1"),
    ]
