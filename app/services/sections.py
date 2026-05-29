from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from app.middleware import get_request_id
from app.repository import sections as sections_repo
from app.repository.sections import (
    HistoryCursor,
    HistoryPage,
    ReportMeta,
    ReportRead,
    Section,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class SectionsError(Exception):
    def __init__(self, *, code: str, message: str, status: int) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def _section_not_found() -> SectionsError:
    return SectionsError(
        code="section_not_found", message="Section not found", status=404
    )


def _version_mismatch() -> SectionsError:
    return SectionsError(
        code="version_mismatch",
        message="The provided version does not match the current section version",
        status=412,
    )


async def read_report(
    db: AsyncSession, *, meta: ReportMeta
) -> ReportRead:
    sections = await sections_repo.list_sections(db, meta.id)
    return ReportRead(
        id=meta.id,
        company_name=meta.company_name,
        company_url=meta.company_url,
        created_at=meta.created_at,
        sections=sections,
    )


async def read_section(
    db: AsyncSession, *, meta: ReportMeta, section_key: str
) -> Section:
    section = await sections_repo.get_section(
        db, report_id=meta.id, section_key=section_key
    )
    if section is None:
        raise _section_not_found()
    return section


async def write_section(
    db: AsyncSession,
    *,
    meta: ReportMeta,
    editor_user_id: int,
    section_key: str,
    expected_version: int,
    new_content: dict[str, Any],
) -> Section:
    result = await sections_repo.write_section_atomic(
        db,
        report_id=meta.id,
        section_key=section_key,
        expected_version=expected_version,
        new_content=new_content,
        editor_user_id=editor_user_id,
    )
    if not result.section_existed:
        raise _section_not_found()
    if result.version_after is None:
        raise _version_mismatch()
    assert result.updated_at is not None

    await db.commit()

    logger.info(
        json.dumps(
            {
                "request_id": get_request_id(),
                "operation": "section.write",
                "user_id": editor_user_id,
                "report_id": meta.id,
                "section_key": section_key,
                "version_before": expected_version,
                "version_after": result.version_after,
                "source": "human",
            }
        )
    )

    return Section(
        section_key=section_key,
        content=new_content,
        version=result.version_after,
        updated_at=result.updated_at,
        updated_by_user_id=editor_user_id,
    )


async def read_history(
    db: AsyncSession,
    *,
    meta: ReportMeta,
    section_key: str,
    limit: int,
    cursor: HistoryCursor | None,
) -> HistoryPage:
    if await sections_repo.get_section(
        db, report_id=meta.id, section_key=section_key
    ) is None:
        raise _section_not_found()

    rows = await sections_repo.list_section_edits(
        db,
        report_id=meta.id,
        section_key=section_key,
        limit=limit + 1,
        cursor=cursor,
    )

    has_more = len(rows) > limit
    edits = rows[:limit]
    next_cursor: HistoryCursor | None = None
    if has_more:
        last = edits[-1]
        next_cursor = HistoryCursor(ts=last.ts, edit_id=last.id)
    return HistoryPage(edits=edits, next_cursor=next_cursor)
