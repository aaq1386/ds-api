from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.database.models import Conversation, Message, Project


class ConversationService:
    def __init__(self, db: Session):
        self.db = db

    def ensure_project(self, path: str, name: Optional[str] = None) -> "Project":
        p = self.db.execute(select(Project).where(Project.path == path)).scalar_one_or_none()
        if p is None:
            p = Project(name=name or path.rsplit("/", 1)[-1] or path, path=path)
            self.db.add(p)
            self.db.commit()
            self.db.refresh(p)
        else:
            p.last_opened_at = datetime.utcnow()
            self.db.commit()
        return p

    def create(self, title: str = "New chat", project_id: Optional[str] = None) -> "Conversation":
        c = Conversation(title=title, project_id=project_id)
        self.db.add(c)
        self.db.commit()
        self.db.refresh(c)
        return c

    def get(self, conv_id: str) -> "Optional[Conversation]":
        return self.db.get(Conversation, conv_id)

    def list(self, limit: int = 50, offset: int = 0) -> "list[Conversation]":
        stmt = select(Conversation).order_by(desc(Conversation.updated_at)).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def delete(self, conv_id: str) -> bool:
        c = self.get(conv_id)
        if not c:
            return False
        self.db.delete(c)
        self.db.commit()
        return True

    def rename(self, conv_id: str, title: str) -> "Optional[Conversation]":
        c = self.get(conv_id)
        if not c:
            return None
        c.title = title
        c.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(c)
        return c

    def set_deepseek_session(self, conv_id: str, session_id: str) -> None:
        c = self.get(conv_id)
        if c:
            c.deepseek_session_id = session_id
            self.db.commit()

    def set_deepseek_parent_message(self, conv_id: str, message_id: int) -> None:
        c = self.get(conv_id)
        if c:
            c.deepseek_parent_message_id = message_id
            self.db.commit()

    def add_message(self, conv_id: str, role: str, content: str,
                    thinking: Optional[str] = None,
                    tokens: Optional[int] = None) -> "Message":
        m = Message(
            conversation_id=conv_id, role=role, content=content,
            thinking=thinking, tokens=tokens,
        )
        self.db.add(m)
        c = self.get(conv_id)
        if c:
            c.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(m)
        return m

    def get_messages(self, conv_id: str) -> "list[Message]":
        stmt = select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
        return list(self.db.execute(stmt).scalars().all())

    def update_message(self, message_id: str, **fields) -> "Optional[Message]":
        m = self.db.get(Message, message_id)
        if not m:
            return None
        for k, v in fields.items():
            if hasattr(m, k):
                setattr(m, k, v)
        self.db.commit()
        self.db.refresh(m)
        return m
