from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MarketResearchReport, ReportSection, ReportShare


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
