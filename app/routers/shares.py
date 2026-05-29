from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.dependencies import CurrentUserDep, DbSession
from app.enums import SharePermission
from app.services import shares as shares_service

router = APIRouter(prefix="/reports/{report_id}/shares", tags=["shares"])


class CreateShareRequest(BaseModel):
    target_user_id: int = Field(gt=0)
    permission: SharePermission


class ShareResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_id: int
    target_user_id: int
    permission: SharePermission
    granted_by_user_id: int
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()


def _http_error(err: shares_service.SharesError) -> HTTPException:
    return HTTPException(
        status_code=err.status,
        detail={"error": err.code, "message": err.message},
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ShareResponse,
)
async def create_share(
    report_id: Annotated[int, Path(gt=0)],
    body: CreateShareRequest,
    current_user: CurrentUserDep,
    db: DbSession,
) -> ShareResponse:
    try:
        share = await shares_service.create_share(
            db,
            actor_user_id=current_user.user_id,
            actor_org_id=current_user.org_id,
            report_id=report_id,
            target_user_id=body.target_user_id,
            permission=body.permission,
        )
    except shares_service.SharesError as err:
        raise _http_error(err) from err
    return ShareResponse.model_validate(share)


@router.delete("/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(
    report_id: Annotated[int, Path(gt=0)],
    share_id: Annotated[int, Path(gt=0)],
    current_user: CurrentUserDep,
    db: DbSession,
) -> Response:
    try:
        await shares_service.revoke_share(
            db,
            actor_user_id=current_user.user_id,
            report_id=report_id,
            share_id=share_id,
        )
    except shares_service.SharesError as err:
        raise _http_error(err) from err
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=list[ShareResponse])
async def list_shares(
    report_id: Annotated[int, Path(gt=0)],
    current_user: CurrentUserDep,
    db: DbSession,
) -> list[ShareResponse]:
    try:
        shares = await shares_service.list_shares(
            db,
            actor_user_id=current_user.user_id,
            report_id=report_id,
        )
    except shares_service.SharesError as err:
        raise _http_error(err) from err
    return [ShareResponse.model_validate(s) for s in shares]
