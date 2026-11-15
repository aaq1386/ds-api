import asyncio
from typing import AsyncIterator, Optional

from app.providers.base import LLMProvider, StreamEvent
from app.providers.deepseek.client import (
    DeepSeekClient, RateLimitError, APIError, NetworkError,
)
from app.security.secrets import redact


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def __init__(self, auth_token: str, cookies: Optional[dict] = None,
                 user_agent: Optional[str] = None,
                 session_id: Optional[str] = None,
                 parent_message_id: Optional[int] = None):
        self._client = DeepSeekClient(auth_token=auth_token, cookies=cookies, user_agent=user_agent)
        self._session_id: Optional[str] = session_id
        self._parent_message_id: Optional[int] = parent_message_id
        self._lock = asyncio.Lock()

    async def ensure_session(self) -> str:
        async with self._lock:
            if self._session_id:
                return self._session_id
            for attempt in range(3):
                try:
                    sid = await asyncio.to_thread(self._client.create_session)
                    self._session_id = sid
                    return sid
                except (NetworkError, RateLimitError, APIError):
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1.5 * (attempt + 1))
            raise APIError("could not create session")

    async def chat(self, prompt: str, history=None, thinking: bool = True,
                   search: bool = False,
                   file_ids: Optional[list[str]] = None) -> AsyncIterator[StreamEvent]:
        session_id = await self.ensure_session()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL = object()

        def producer():
            try:
                for ev in self._client.stream_chat(
                    chat_session_id=session_id, prompt=prompt,
                    parent_message_id=self._parent_message_id,
                    thinking_enabled=thinking, search_enabled=search,
                    ref_file_ids=file_ids or [],
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, ev)
            except Exception as exc:
                loop.call_soon_threadsafe(
                    queue.put_nowait, {"type": "error", "content": redact(str(exc))}
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

        loop.run_in_executor(None, producer)

        text_parts = []
        thinking_parts = []

        while True:
            ev = await queue.get()
            if ev is SENTINEL:
                break
            t = ev.get("type")
            if t == "message_id":
                yield StreamEvent(
                    type="message_id",
                    meta={"message_id": ev.get("message_id")},
                )
            elif t == "text":
                content = ev.get("content", "")
                text_parts.append(content)
                yield StreamEvent(type="text", content=content)
            elif t == "thinking":
                content = ev.get("content", "")
                thinking_parts.append(content)
                yield StreamEvent(type="thinking", content=content)
            elif t == "fragment":
                content = ev.get("content", "")
                if not content:
                    continue
                if thinking and not text_parts:
                    thinking_parts.append(content)
                    yield StreamEvent(type="thinking", content=content)
                else:
                    text_parts.append(content)
                    yield StreamEvent(type="text", content=content)
            elif t == "done":
                yield StreamEvent(type="done")
                return
            elif t == "error":
                yield StreamEvent(type="error", content=ev.get("content", ""))

    async def upload_file(self, file_path: str) -> str:
        return await asyncio.to_thread(self._client.upload_file, file_path)

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)
