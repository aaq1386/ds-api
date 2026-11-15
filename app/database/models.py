import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Text, Integer, DateTime, ForeignKey, JSON, Boolean, Float
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.utcnow()


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    language: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    framework: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(255), default="New chat")
    project_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(32), default="deepseek")
    deepseek_session_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    deepseek_parent_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    project: Mapped[Optional[Project]] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    thinking: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    goal: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentStep.index"
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    index: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(32), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    run: Mapped[AgentRun] = relationship(back_populates="steps")
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        back_populates="step", cascade="all, delete-orphan"
    )


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    step_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_steps.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    step: Mapped[AgentStep] = relationship(back_populates="tool_calls")


class FileChange(Base):
    __tablename__ = "file_changes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    change_type: Mapped[str] = mapped_column(String(16), default="edit")
    diff: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
