from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Response,
)
from pydantic import BaseModel, ConfigDict, field_serializer

from app.dependencies import CurrentUserDep, DbSession
from app.repository import sections as sections_repo
from app.repository.sections import ReportMeta
from app.services import sections as sections_service

router = APIRouter(prefix="/reports", tags=["sections"])


async def require_view_access(
    report_id: Annotated[int, Path(gt=0)],
    current_user: CurrentUserDep,
    db: DbSession,
) -> ReportMeta:
    meta = await sections_repo.get_report_meta(db, report_id)
    if meta is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "report_not_found", "message": "Report not found"},
        )
    if meta.owner_user_id == current_user.user_id:
        return meta
    if await sections_repo.has_active_share(
        db, report_id=report_id, user_id=current_user.user_id
    ):
        return meta
    raise HTTPException(
        status_code=403,
        detail={
            "error": "forbidden",
            "message": "You do not have access to this report",
        },
    )


async def require_edit_access(
    report_id: Annotated[int, Path(gt=0)],
    current_user: CurrentUserDep,
    db: DbSession,
) -> ReportMeta:
    meta = await sections_repo.get_report_meta(db, report_id)
    if meta is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "report_not_found", "message": "Report not found"},
        )
    if meta.owner_user_id == current_user.user_id:
        return meta
    if await sections_repo.has_edit_share(
        db, report_id=report_id, user_id=current_user.user_id
    ):
        return meta
    raise HTTPException(
        status_code=403,
        detail={
            "error": "forbidden",
            "message": "You do not have edit access to this report",
        },
    )


def require_if_match(
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> int:
    if if_match is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "if_match_required",
                "message": "If-Match header is required",
            },
        )
    if len(if_match) < 3 or if_match[0] != '"' or if_match[-1] != '"':
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_if_match",
                "message": 'If-Match must be a strong quoted validator, e.g. "3"',
            },
        )
    try:
        return int(if_match[1:-1])
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_if_match",
                "message": "If-Match version must be an integer",
            },
        )


ViewAccess = Annotated[ReportMeta, Depends(require_view_access)]
EditAccess = Annotated[ReportMeta, Depends(require_edit_access)]
IfMatch = Annotated[int, Depends(require_if_match)]


class SectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    section_key: str
    content: dict[str, Any]
    version: int
    updated_at: datetime
    updated_by_user_id: int

    @field_serializer("updated_at")
    def _serialize_updated_at(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_name: str | None
    company_url: str | None
    created_at: datetime
    sections: list[SectionResponse]

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()


class UpdateSectionRequest(BaseModel):
    content: dict[str, Any]


def _http_error(err: sections_service.SectionsError) -> HTTPException:
    return HTTPException(
        status_code=err.status,
        detail={"error": err.code, "message": err.message},
    )


@router.get("/{report_id}", response_model=ReportResponse)
async def read_report(
    meta: ViewAccess,
    db: DbSession,
) -> ReportResponse:
    report = await sections_service.read_report(db, meta=meta)
    return ReportResponse.model_validate(report)


@router.get(
    "/{report_id}/sections/{section_key}",
    response_model=SectionResponse,
)
async def read_section(
    meta: ViewAccess,
    section_key: Annotated[str, Path(min_length=1)],
    db: DbSession,
    response: Response,
) -> SectionResponse:
    try:
        section = await sections_service.read_section(
            db, meta=meta, section_key=section_key
        )
    except sections_service.SectionsError as err:
        raise _http_error(err) from err
    response.headers["ETag"] = f'"{section.version}"'
    return SectionResponse.model_validate(section)


@router.patch(
    "/{report_id}/sections/{section_key}",
    response_model=SectionResponse,
)
async def write_section(
    meta: EditAccess,
    section_key: Annotated[str, Path(min_length=1)],
    body: UpdateSectionRequest,
    if_match: IfMatch,
    current_user: CurrentUserDep,
    db: DbSession,
    response: Response,
) -> SectionResponse:
    try:
        section = await sections_service.write_section(
            db,
            meta=meta,
            editor_user_id=current_user.user_id,
            section_key=section_key,
            expected_version=if_match,
            new_content=body.content,
        )
    except sections_service.SectionsError as err:
        raise _http_error(err) from err
    response.headers["ETag"] = f'"{section.version}"'
    return SectionResponse.model_validate(section)
