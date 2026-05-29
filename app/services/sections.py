from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from app.enums import EditSource
from app.llm_client import LLMClient, LLMMessage
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


def _edit_not_found() -> SectionsError:
    return SectionsError(
        code="edit_not_found",
        message="Edit not found for this section",
        status=404,
    )


def _llm_call_failed() -> SectionsError:
    return SectionsError(
        code="llm_call_failed",
        message="LLM provider call failed",
        status=502,
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
        source=EditSource.human,
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


async def ai_rewrite_section(
    db: AsyncSession,
    *,
    meta: ReportMeta,
    editor_user_id: int,
    section_key: str,
    expected_version: int,
    instruction: str,
    llm_client: LLMClient,
) -> Section:
    section = await sections_repo.get_section(
        db, report_id=meta.id, section_key=section_key
    )
    if section is None:
        raise _section_not_found()
    if section.version != expected_version:
        raise _version_mismatch()

    await db.commit()

    messages = [
        LLMMessage(
            role="system",
            content=f"Current section content: {json.dumps(section.content)}",
        ),
        LLMMessage(role="user", content=instruction),
    ]
    try:
        llm_response = await llm_client.call(
            operation="report.section.ai_rewrite",
            request_id=get_request_id(),
            messages=messages,
        )
    except Exception as exc:
        raise _llm_call_failed() from exc

    new_content: dict[str, Any] = {"text": llm_response.content}
    result = await sections_repo.write_section_atomic(
        db,
        report_id=meta.id,
        section_key=section_key,
        expected_version=expected_version,
        new_content=new_content,
        editor_user_id=editor_user_id,
        source=EditSource.ai_rewrite,
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
                "operation": "section.ai_rewrite",
                "user_id": editor_user_id,
                "report_id": meta.id,
                "section_key": section_key,
                "version_before": expected_version,
                "version_after": result.version_after,
                "source": "ai_rewrite",
                "input_tokens": llm_response.input_tokens,
                "output_tokens": llm_response.output_tokens,
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


async def revert_section(
    db: AsyncSession,
    *,
    meta: ReportMeta,
    editor_user_id: int,
    section_key: str,
    target_edit_id: int,
) -> Section:
    result = await sections_repo.revert_section_atomic(
        db,
        report_id=meta.id,
        section_key=section_key,
        target_edit_id=target_edit_id,
        editor_user_id=editor_user_id,
    )
    if not result.edit_existed:
        raise _edit_not_found()
    if not result.section_existed:
        raise _section_not_found()
    assert result.version_after is not None
    assert result.updated_at is not None
    assert result.new_content is not None

    await db.commit()

    logger.info(
        json.dumps(
            {
                "request_id": get_request_id(),
                "operation": "section.revert",
                "user_id": editor_user_id,
                "report_id": meta.id,
                "section_key": section_key,
                "target_edit_id": target_edit_id,
                "version_after": result.version_after,
                "source": "revert",
            }
        )
    )

    return Section(
        section_key=section_key,
        content=result.new_content,
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
