"""لایه انتزاعی Provider — امکان تعویض DeepSeek با هر Provider دیگر."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class StreamEvent:
    type: str
    content: str = ""
    meta: Optional[dict] = None


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def ensure_session(self) -> str:
        ...

    @abstractmethod
    async def chat(
        self,
        prompt: str,
        history: list[ChatMessage] | None = None,
        thinking: bool = True,
        search: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...
