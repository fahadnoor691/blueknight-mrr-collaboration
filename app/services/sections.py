from __future__ import annotations

from typing import TYPE_CHECKING

from app.repository import sections as sections_repo
from app.repository.sections import ReportMeta, ReportRead, Section

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SectionsError(Exception):
    def __init__(self, *, code: str, message: str, status: int) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def _report_not_found() -> SectionsError:
    return SectionsError(
        code="report_not_found", message="Report not found", status=404
    )


def _forbidden() -> SectionsError:
    return SectionsError(
        code="forbidden",
        message="You do not have access to this report",
        status=403,
    )


def _section_not_found() -> SectionsError:
    return SectionsError(
        code="section_not_found", message="Section not found", status=404
    )


async def _ensure_access(
    db: AsyncSession, *, actor_user_id: int, report_id: int
) -> ReportMeta:
    meta = await sections_repo.get_report_meta(db, report_id)
    if meta is None:
        raise _report_not_found()
    if meta.owner_user_id == actor_user_id:
        return meta
    if await sections_repo.has_active_share(
        db, report_id=report_id, user_id=actor_user_id
    ):
        return meta
    raise _forbidden()


async def read_report(
    db: AsyncSession, *, actor_user_id: int, report_id: int
) -> ReportRead:
    meta = await _ensure_access(
        db, actor_user_id=actor_user_id, report_id=report_id
    )
    sections = await sections_repo.list_sections(db, report_id)
    return ReportRead(
        id=meta.id,
        company_name=meta.company_name,
        company_url=meta.company_url,
        created_at=meta.created_at,
        sections=sections,
    )


async def read_section(
    db: AsyncSession,
    *,
    actor_user_id: int,
    report_id: int,
    section_key: str,
) -> Section:
    await _ensure_access(
        db, actor_user_id=actor_user_id, report_id=report_id
    )
    section = await sections_repo.get_section(
        db, report_id=report_id, section_key=section_key
    )
    if section is None:
        raise _section_not_found()
    return section
