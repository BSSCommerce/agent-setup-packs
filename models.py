"""Database models for Agent Setup Packs installations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AgentSetupPackInstallation(Base):
    """One recorded setup run for a template pack."""

    __tablename__ = "plugin_agent_setup_pack_installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.1.0")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_agent_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_flow_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_deep_agent_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    options_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    resources: Mapped[list[AgentSetupPackResourceMap]] = relationship(
        back_populates="installation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AgentSetupPackResourceMap(Base):
    """Maps logical template keys to created Agent Manager resources."""

    __tablename__ = "plugin_agent_setup_pack_resource_map"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "logical_key",
            name="uq_setup_pack_resource_installation_logical",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    installation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("plugin_agent_setup_pack_installations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    logical_key: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    alias: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    installation: Mapped[AgentSetupPackInstallation] = relationship(back_populates="resources")
