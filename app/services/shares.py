from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from app.enums import SharePermission
from app.middleware import get_request_id
from app.repository import shares as shares_repo
from app.repository.shares import Share

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class SharesError(Exception):
    def __init__(self, *, code: str, message: str, status: int) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def _report_not_found() -> SharesError:
    return SharesError(
        code="report_not_found", message="Report not found", status=404
    )


def _forbidden() -> SharesError:
    return SharesError(
        code="forbidden",
        message="Only the report owner can manage shares",
        status=403,
    )


def _cross_org() -> SharesError:
    return SharesError(
        code="cross_org_share_forbidden",
        message="Cannot share a report across organizations",
        status=403,
    )


def _target_user_not_found() -> SharesError:
    return SharesError(
        code="target_user_not_found",
        message="Target user not found",
        status=404,
    )


def _duplicate_share() -> SharesError:
    return SharesError(
        code="share_already_exists",
        message="An active share for this user already exists",
        status=409,
    )


def _share_not_found() -> SharesError:
    return SharesError(
        code="share_not_found", message="Share not found", status=404
    )


async def _assert_owner(
    db: AsyncSession, *, actor_user_id: int, report_id: int
) -> None:
    ownership = await shares_repo.get_report_with_owner_org(db, report_id)
    if ownership is None:
        raise _report_not_found()
    if ownership.owner_user_id != actor_user_id:
        raise _forbidden()


async def create_share(
    db: AsyncSession,
    *,
    actor_user_id: int,
    actor_org_id: int,
    report_id: int,
    target_user_id: int,
    permission: SharePermission,
) -> Share:
    await _assert_owner(db, actor_user_id=actor_user_id, report_id=report_id)

    target = await shares_repo.get_user_org(db, target_user_id)
    if target is None:
        raise _target_user_not_found()
    if target.org_id != actor_org_id:
        raise _cross_org()

    share = await shares_repo.create_share(
        db,
        report_id=report_id,
        target_user_id=target_user_id,
        permission=permission,
        granted_by_user_id=actor_user_id,
    )
    if share is None:
        raise _duplicate_share()

    await db.commit()

    logger.info(
        json.dumps(
            {
                "request_id": get_request_id(),
                "operation": "share.create",
                "user_id": actor_user_id,
                "report_id": report_id,
                "share_id": share.id,
                "target_user_id": target_user_id,
                "permission": permission.value,
            }
        )
    )
    return share


async def revoke_share(
    db: AsyncSession,
    *,
    actor_user_id: int,
    report_id: int,
    share_id: int,
) -> None:
    await _assert_owner(db, actor_user_id=actor_user_id, report_id=report_id)

    found = await shares_repo.revoke_share(
        db, report_id=report_id, share_id=share_id
    )
    if not found:
        raise _share_not_found()

    await db.commit()

    logger.info(
        json.dumps(
            {
                "request_id": get_request_id(),
                "operation": "share.revoke",
                "user_id": actor_user_id,
                "report_id": report_id,
                "share_id": share_id,
            }
        )
    )


async def list_shares(
    db: AsyncSession,
    *,
    actor_user_id: int,
    report_id: int,
) -> list[Share]:
    await _assert_owner(db, actor_user_id=actor_user_id, report_id=report_id)
    return await shares_repo.list_active_shares(db, report_id)
