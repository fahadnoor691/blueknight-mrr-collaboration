import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)



class EditSource(str, enum.Enum):
    human = "human"
    ai_rewrite = "ai_rewrite"
    revert = "revert"


class SharePermission(str, enum.Enum):
    view = "view"
    edit = "edit"


class User(Base):
    __tablename__ = "users"

    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)

    reports: Mapped[list["MarketResearchReport"]] = relationship(
        back_populates="owner",
        passive_deletes=True,
    )


class MarketResearchReport(Base):
    __tablename__ = "market_research_reports"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=True)
    company_url: Mapped[str] = mapped_column(String(2048), nullable=True)
    sections: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    owner: Mapped["User"] = relationship(back_populates="reports")

    sections_list: Mapped[list["ReportSection"]] = relationship(passive_deletes=True)
    shares: Mapped[list["ReportShare"]] = relationship(passive_deletes=True)




class ReportSection(Base):
    __tablename__ = "report_sections"
    __table_args__ = (
        UniqueConstraint(
            "report_id",
            "section_key",
            name="report_sections_report_id_section_key_key",
        ),
    )

    report_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("market_research_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    section_key: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    report: Mapped["MarketResearchReport"] = relationship()
    updated_by: Mapped["User"] = relationship()


class ReportSectionEdit(Base):
    __tablename__ = "report_section_edits"
    __table_args__ = (
        Index(
            "report_section_edits_history_idx",
            "report_id",
            "section_key",
            desc("ts"),
        ),
    )

    report_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("market_research_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    section_key: Mapped[str] = mapped_column(Text, nullable=False)
    version_before: Mapped[int] = mapped_column(Integer, nullable=False)
    version_after: Mapped[int] = mapped_column(Integer, nullable=False)
    content_before: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_after: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    editor_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source: Mapped[EditSource] = mapped_column(
        Enum(
            EditSource,
            name="edit_source",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    report: Mapped["MarketResearchReport"] = relationship()
    editor: Mapped["User"] = relationship()


class ReportShare(Base):
    __tablename__ = "report_shares"
    __table_args__ = (
        Index(
            "report_shares_active_uniq",
            "report_id",
            "target_user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    report_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("market_research_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    permission: Mapped[SharePermission] = mapped_column(
        Enum(
            SharePermission,
            name="share_permission",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    granted_by_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    report: Mapped["MarketResearchReport"] = relationship()
    target_user: Mapped["User"] = relationship(foreign_keys=[target_user_id])
    granted_by: Mapped["User"] = relationship(foreign_keys=[granted_by_user_id])