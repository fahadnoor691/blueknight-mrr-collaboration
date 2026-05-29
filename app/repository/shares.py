from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import SharePermission
from app.models import MarketResearchReport, ReportShare, User


@dataclass(frozen=True)
class ReportOwnership:
    report_id: int
    owner_user_id: int
    owner_org_id: int


@dataclass(frozen=True)
class UserOrg:
    user_id: int
    org_id: int


@dataclass(frozen=True)
class Share:
    id: int
    report_id: int
    target_user_id: int
    permission: SharePermission
    granted_by_user_id: int
    created_at: datetime


async def get_report_with_owner_org(
    db: AsyncSession, report_id: int
) -> ReportOwnership | None:
    stmt = (
        select(MarketResearchReport.id, MarketResearchReport.user_id, User.org_id)
        .join(User, User.id == MarketResearchReport.user_id)
        .where(MarketResearchReport.id == report_id)
    )
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        return None
    return ReportOwnership(
        report_id=row[0], owner_user_id=row[1], owner_org_id=row[2]
    )


async def get_user_org(db: AsyncSession, user_id: int) -> UserOrg | None:
    stmt = select(User.id, User.org_id).where(User.id == user_id)
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        return None
    return UserOrg(user_id=row[0], org_id=row[1])


async def create_share(
    db: AsyncSession,
    *,
    report_id: int,
    target_user_id: int,
    permission: SharePermission,
    granted_by_user_id: int,
) -> Share | None:
    orm = ReportShare(
        report_id=report_id,
        target_user_id=target_user_id,
        permission=permission,
        granted_by_user_id=granted_by_user_id,
    )
    db.add(orm)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return None
    return Share(
        id=orm.id,
        report_id=orm.report_id,
        target_user_id=orm.target_user_id,
        permission=orm.permission,
        granted_by_user_id=orm.granted_by_user_id,
        created_at=orm.created_at,
    )


async def revoke_share(
    db: AsyncSession, *, report_id: int, share_id: int
) -> bool:
    """Revoke if active. Returns True iff the share belongs to the report
    (whether or not this call mutated it). False means 404."""
    update_stmt = (
        update(ReportShare)
        .where(
            ReportShare.id == share_id,
            ReportShare.report_id == report_id,
            ReportShare.revoked_at.is_(None),
        )
        .values(revoked_at=func.now())
        .returning(ReportShare.id)
    )
    if (await db.execute(update_stmt)).scalar_one_or_none() is not None:
        return True
    exists_stmt = select(ReportShare.id).where(
        ReportShare.id == share_id,
        ReportShare.report_id == report_id,
    )
    return (await db.execute(exists_stmt)).scalar_one_or_none() is not None


async def list_active_shares(
    db: AsyncSession, report_id: int
) -> list[Share]:
    stmt = (
        select(ReportShare)
        .where(
            ReportShare.report_id == report_id,
            ReportShare.revoked_at.is_(None),
        )
        .order_by(ReportShare.created_at)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        Share(
            id=s.id,
            report_id=s.report_id,
            target_user_id=s.target_user_id,
            permission=s.permission,
            granted_by_user_id=s.granted_by_user_id,
            created_at=s.created_at,
        )
        for s in rows
    ]
