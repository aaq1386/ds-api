from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_conversation_service
from app.services.conversation import ConversationService

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str = "New chat"
    project_id: Optional[str] = None


class ConversationUpdate(BaseModel):
    title: str


class ConversationOut(BaseModel):
    id: str
    title: str
    project_id: Optional[str] = None
    provider: str
    created_at: str
    updated_at: str


def _to_out(c) -> ConversationOut:
    return ConversationOut(
        id=c.id, title=c.title, project_id=c.project_id, provider=c.provider,
        created_at=c.created_at.isoformat(), updated_at=c.updated_at.isoformat(),
    )


@router.post("", response_model=ConversationOut)
def create_conversation(body: ConversationCreate,
                        svc: ConversationService = Depends(get_conversation_service)):
    c = svc.create(title=body.title, project_id=body.project_id)
    return _to_out(c)


@router.get("", response_model=list[ConversationOut])
def list_conversations(limit: int = Query(50, ge=1, le=200),
                       offset: int = Query(0, ge=0),
                       svc: ConversationService = Depends(get_conversation_service)):
    return [_to_out(c) for c in svc.list(limit=limit, offset=offset)]


@router.get("/{conv_id}", response_model=ConversationOut)
def get_conversation(conv_id: str,
                     svc: ConversationService = Depends(get_conversation_service)):
    c = svc.get(conv_id)
    if not c:
        raise HTTPException(404, "conversation not found")
    return _to_out(c)


@router.patch("/{conv_id}", response_model=ConversationOut)
def rename_conversation(conv_id: str, body: ConversationUpdate,
                        svc: ConversationService = Depends(get_conversation_service)):
    c = svc.rename(conv_id, body.title)
    if not c:
        raise HTTPException(404, "conversation not found")
    return _to_out(c)


@router.delete("/{conv_id}")
def delete_conversation(conv_id: str,
                        svc: ConversationService = Depends(get_conversation_service)):
    ok = svc.delete(conv_id)
    if not ok:
        raise HTTPException(404, "conversation not found")
    return {"ok": True}


@router.get("/{conv_id}/messages")
def get_messages(conv_id: str,
                 svc: ConversationService = Depends(get_conversation_service)):
    c = svc.get(conv_id)
    if not c:
        raise HTTPException(404, "conversation not found")
    msgs = svc.get_messages(conv_id)
    return [
        {
            "id": m.id, "role": m.role, "content": m.content,
            "thinking": m.thinking, "created_at": m.created_at.isoformat(),
        }
        for m in msgs
    ]
