from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, select, text, tuple_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import EditSource, SharePermission
from app.models import (
    MarketResearchReport,
    ReportSection,
    ReportSectionEdit,
    ReportShare,
)


@dataclass(frozen=True)
class ReportMeta:
    id: int
    owner_user_id: int
    company_name: str | None
    company_url: str | None
    created_at: datetime


@dataclass(frozen=True)
class Section:
    section_key: str
    content: dict[str, Any]
    version: int
    updated_at: datetime
    updated_by_user_id: int


@dataclass(frozen=True)
class ReportRead:
    id: int
    company_name: str | None
    company_url: str | None
    created_at: datetime
    sections: list[Section]


@dataclass(frozen=True)
class WriteResult:
    section_existed: bool
    version_after: int | None
    updated_at: datetime | None


@dataclass(frozen=True)
class HistoryCursor:
    ts: datetime
    edit_id: int


@dataclass(frozen=True)
class Edit:
    id: int
    version_before: int
    version_after: int
    content_before: dict[str, Any]
    content_after: dict[str, Any]
    editor_user_id: int
    source: EditSource
    ts: datetime


@dataclass(frozen=True)
class HistoryPage:
    edits: list[Edit]
    next_cursor: HistoryCursor | None


@dataclass(frozen=True)
class RevertResult:
    edit_existed: bool
    section_existed: bool
    version_after: int | None
    updated_at: datetime | None
    new_content: dict[str, Any] | None


async def get_report_meta(
    db: AsyncSession, report_id: int
) -> ReportMeta | None:
    stmt = select(
        MarketResearchReport.id,
        MarketResearchReport.user_id,
        MarketResearchReport.company_name,
        MarketResearchReport.company_url,
        MarketResearchReport.created_at,
    ).where(MarketResearchReport.id == report_id)
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        return None
    return ReportMeta(
        id=row[0],
        owner_user_id=row[1],
        company_name=row[2],
        company_url=row[3],
        created_at=row[4],
    )


async def has_active_share(
    db: AsyncSession, *, report_id: int, user_id: int
) -> bool:
    stmt = (
        select(ReportShare.id)
        .where(
            ReportShare.report_id == report_id,
            ReportShare.target_user_id == user_id,
            ReportShare.revoked_at.is_(None),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def has_edit_share(
    db: AsyncSession, *, report_id: int, user_id: int
) -> bool:
    stmt = (
        select(ReportShare.id)
        .where(
            ReportShare.report_id == report_id,
            ReportShare.target_user_id == user_id,
            ReportShare.permission == SharePermission.edit,
            ReportShare.revoked_at.is_(None),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def list_sections(
    db: AsyncSession, report_id: int
) -> list[Section]:
    stmt = (
        select(ReportSection)
        .where(ReportSection.report_id == report_id)
        .order_by(ReportSection.section_key)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        Section(
            section_key=s.section_key,
            content=s.content,
            version=s.version,
            updated_at=s.updated_at,
            updated_by_user_id=s.updated_by_user_id,
        )
        for s in rows
    ]


async def get_section(
    db: AsyncSession, *, report_id: int, section_key: str
) -> Section | None:
    stmt = select(ReportSection).where(
        ReportSection.report_id == report_id,
        ReportSection.section_key == section_key,
    )
    s = (await db.execute(stmt)).scalar_one_or_none()
    if s is None:
        return None
    return Section(
        section_key=s.section_key,
        content=s.content,
        version=s.version,
        updated_at=s.updated_at,
        updated_by_user_id=s.updated_by_user_id,
    )


_WRITE_SECTION_SQL = text(
    """
WITH prior AS (
    SELECT content AS content_before
    FROM report_sections
    WHERE report_id = :report_id AND section_key = :section_key
),
updated AS (
    UPDATE report_sections
    SET content = :new_content,
        version = version + 1,
        updated_at = now(),
        updated_by_user_id = :editor_user_id
    WHERE report_id = :report_id
      AND section_key = :section_key
      AND version = :expected_version
    RETURNING version, updated_at
),
audit AS (
    INSERT INTO report_section_edits (
        report_id, section_key,
        version_before, version_after,
        content_before, content_after,
        editor_user_id, source
    )
    SELECT :report_id, :section_key,
           :expected_version, updated.version,
           prior.content_before, :new_content,
           :editor_user_id, CAST(:source AS edit_source)
    FROM updated, prior
    RETURNING id
)
SELECT
    EXISTS (SELECT 1 FROM prior)        AS section_existed,
    (SELECT version    FROM updated)    AS version_after,
    (SELECT updated_at FROM updated)    AS updated_at
"""
).bindparams(bindparam("new_content", type_=JSONB))


async def write_section_atomic(
    db: AsyncSession,
    *,
    report_id: int,
    section_key: str,
    expected_version: int,
    new_content: dict[str, Any],
    editor_user_id: int,
    source: EditSource,
) -> WriteResult:
    row = (
        await db.execute(
            _WRITE_SECTION_SQL,
            {
                "report_id": report_id,
                "section_key": section_key,
                "expected_version": expected_version,
                "new_content": new_content,
                "editor_user_id": editor_user_id,
                "source": source.value,
            },
        )
    ).one()
    return WriteResult(
        section_existed=row[0],
        version_after=row[1],
        updated_at=row[2],
    )


_REVERT_SECTION_SQL = text(
    """
WITH target_edit AS (
    SELECT content_before AS revert_content
    FROM report_section_edits
    WHERE id = :edit_id
      AND report_id = :report_id
      AND section_key = :section_key
),
prior AS (
    SELECT content AS content_before, version AS version_before
    FROM report_sections
    WHERE report_id = :report_id AND section_key = :section_key
    FOR UPDATE
),
updated AS (
    UPDATE report_sections
    SET content = (SELECT revert_content FROM target_edit),
        version = version + 1,
        updated_at = now(),
        updated_by_user_id = :editor_user_id
    WHERE report_id = :report_id
      AND section_key = :section_key
      AND EXISTS (SELECT 1 FROM target_edit)
    RETURNING version, updated_at
),
audit AS (
    INSERT INTO report_section_edits (
        report_id, section_key,
        version_before, version_after,
        content_before, content_after,
        editor_user_id, source
    )
    SELECT :report_id, :section_key,
           prior.version_before, updated.version,
           prior.content_before, target_edit.revert_content,
           :editor_user_id, 'revert'::edit_source
    FROM updated, prior, target_edit
    RETURNING id
)
SELECT
    EXISTS (SELECT 1 FROM target_edit)        AS edit_existed,
    EXISTS (SELECT 1 FROM prior)              AS section_existed,
    (SELECT version       FROM updated)       AS version_after,
    (SELECT updated_at    FROM updated)       AS updated_at,
    (SELECT revert_content FROM target_edit)  AS new_content
"""
)


async def revert_section_atomic(
    db: AsyncSession,
    *,
    report_id: int,
    section_key: str,
    target_edit_id: int,
    editor_user_id: int,
) -> RevertResult:
    row = (
        await db.execute(
            _REVERT_SECTION_SQL,
            {
                "report_id": report_id,
                "section_key": section_key,
                "edit_id": target_edit_id,
                "editor_user_id": editor_user_id,
            },
        )
    ).one()
    return RevertResult(
        edit_existed=row[0],
        section_existed=row[1],
        version_after=row[2],
        updated_at=row[3],
        new_content=row[4],
    )


async def list_section_edits(
    db: AsyncSession,
    *,
    report_id: int,
    section_key: str,
    limit: int,
    cursor: HistoryCursor | None,
) -> list[Edit]:
    stmt = select(ReportSectionEdit).where(
        ReportSectionEdit.report_id == report_id,
        ReportSectionEdit.section_key == section_key,
    )
    if cursor is not None:
        stmt = stmt.where(
            tuple_(ReportSectionEdit.ts, ReportSectionEdit.id)
            < tuple_(cursor.ts, cursor.edit_id)
        )
    stmt = stmt.order_by(
        ReportSectionEdit.ts.desc(),
        ReportSectionEdit.id.desc(),
    ).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        Edit(
            id=r.id,
            version_before=r.version_before,
            version_after=r.version_after,
            content_before=r.content_before,
            content_after=r.content_after,
            editor_user_id=r.editor_user_id,
            source=r.source,
            ts=r.ts,
        )
        for r in rows
    ]
