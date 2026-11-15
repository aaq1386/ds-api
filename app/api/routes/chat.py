import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import get_conversation_service
from app.providers.deepseek import DeepSeekProvider
from app.services.auth import AuthManager
from app.services.conversation import ConversationService
from app.services.streaming import sse_event
from app.database import SessionLocal
from app.security.secrets import redact

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger("chat")


class ChatRequest(BaseModel):
    conversation_id: str
    prompt: str
    thinking: bool = False
    search: bool = False
    file_ids: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    conversation_id: str
    text: str
    thinking: str | None = None
    ok: bool = True


def _build_provider(
    session_id: str | None = None,
    parent_message_id: int | None = None,
) -> DeepSeekProvider:
    auth = AuthManager()
    cookies = auth.load_cookies()
    token = cookies.get("ds_session_id")
    if not token:
        raise HTTPException(401, "No ds_session_id in config/cookies.json")
    return DeepSeekProvider(
        auth_token=token,
        cookies=cookies,
        user_agent=auth.load_user_agent() or None,
        session_id=session_id,
        parent_message_id=parent_message_id,
    )


def _prepare(body: ChatRequest, svc: ConversationService):
    conv = svc.get(body.conversation_id)
    if not conv:
        raise HTTPException(404, "conversation not found")
    if not body.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    svc.add_message(conv.id, role="user", content=body.prompt)
    return conv.id, conv.title




MAX_UPLOAD_SIZE = 20 * 1024 * 1024


@router.post("/upload")
async def upload_chat_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "filename is required")

    suffix = Path(file.filename).suffix[:16]
    temp_path = None
    provider = None
    size = 0

    try:
        fd, temp_path = tempfile.mkstemp(prefix="ds-upload-", suffix=suffix)
        os.close(fd)

        with open(temp_path, "wb") as destination:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break

                size += len(chunk)
                if size > MAX_UPLOAD_SIZE:
                    raise HTTPException(413, "File exceeds 20 MB limit")

                destination.write(chunk)

        if size == 0:
            raise HTTPException(400, "Empty files are not allowed")

        provider = _build_provider()
        file_id = await provider.upload_file(temp_path)

        return {
            "ok": True,
            "file_id": file_id,
            "filename": file.filename,
            "size": size,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("file upload failed")
        raise HTTPException(502, f"DeepSeek upload failed: {redact(str(exc))}")
    finally:
        await file.close()

        if provider is not None:
            await provider.close()

        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


@router.post("/stream")
async def chat_stream(body: ChatRequest, svc: ConversationService = Depends(get_conversation_service)):
    conv = svc.get(body.conversation_id)
    conv_id, conv_title = _prepare(body, svc)
    provider = _build_provider(conv.deepseek_session_id, conv.deepseek_parent_message_id)

    async def event_generator():
        text_parts = []
        thinking_parts = []
        last_message_id = None
        try:
            try:
                sid = await provider.ensure_session()
            except Exception as e:
                logger.exception("ensure_session failed")
                yield sse_event("error", {"message": redact(str(e))})
                yield sse_event("done", {"ok": False})
                return

            yield sse_event("start", {"conversation_id": conv_id})

            async for ev in provider.chat(
                prompt=body.prompt,
                thinking=body.thinking,
                search=body.search,
                file_ids=body.file_ids,
            ):
                if ev.type == "text":
                    text_parts.append(ev.content)
                    yield sse_event("text", {"content": ev.content})
                elif ev.type == "thinking":
                    thinking_parts.append(ev.content)
                    yield sse_event("thinking", {"content": ev.content})
                elif ev.type == "message_id":
                    last_message_id = ev.meta.get("message_id") if ev.meta else None
                elif ev.type == "error":
                    yield sse_event("error", {"message": redact(ev.content)})
                elif ev.type == "done":
                    break

            final_text = "".join(text_parts)
            final_thinking = "".join(thinking_parts) or None

            db = SessionLocal()
            try:
                svc2 = ConversationService(db)
                svc2.add_message(conv_id, role="assistant", content=final_text, thinking=final_thinking)
                if conv_title in ("New chat", "") and body.prompt:
                    svc2.rename(conv_id, body.prompt.strip().split("\n")[0][:80])
                svc2.set_deepseek_session(conv_id, sid)
                if last_message_id is not None:
                    svc2.set_deepseek_parent_message(conv_id, int(last_message_id))
            finally:
                db.close()

            yield sse_event("done", {"ok": True})
        except Exception as e:
            logger.exception("chat stream failed")
            yield sse_event("error", {"message": redact(str(e))})
            yield sse_event("done", {"ok": False})
        finally:
            await provider.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("", response_model=ChatResponse)
async def chat_non_stream(body: ChatRequest, svc: ConversationService = Depends(get_conversation_service)):
    conv = svc.get(body.conversation_id)
    conv_id, conv_title = _prepare(body, svc)
    provider = _build_provider(conv.deepseek_session_id, conv.deepseek_parent_message_id)
    try:
        text_parts = []
        thinking_parts = []
        last_message_id = None
        try:
            sid = await provider.ensure_session()
        except Exception as e:
            raise HTTPException(502, f"ensure_session failed: {redact(str(e))}")

        async for ev in provider.chat(
                prompt=body.prompt,
                thinking=body.thinking,
                search=body.search,
                file_ids=body.file_ids,
            ):
            if ev.type == "text":
                text_parts.append(ev.content)
            elif ev.type == "thinking":
                thinking_parts.append(ev.content)
            elif ev.type == "message_id":
                last_message_id = ev.meta.get("message_id") if ev.meta else None
            elif ev.type == "error":
                raise HTTPException(502, redact(ev.content))
            elif ev.type == "done":
                break

        final_text = "".join(text_parts)
        final_thinking = "".join(thinking_parts) or None

        db = SessionLocal()
        try:
            svc2 = ConversationService(db)
            svc2.add_message(conv_id, role="assistant", content=final_text, thinking=final_thinking)
            if conv_title in ("New chat", "") and body.prompt:
                svc2.rename(conv_id, body.prompt.strip().split("\n")[0][:80])
            svc2.set_deepseek_session(conv_id, sid)
            if last_message_id is not None:
                svc2.set_deepseek_parent_message(conv_id, int(last_message_id))
        finally:
            db.close()

        return ChatResponse(conversation_id=conv_id, text=final_text, thinking=final_thinking, ok=True)
    finally:
        await provider.close()
