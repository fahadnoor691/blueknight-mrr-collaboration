import base64
import json
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Response,
)
from pydantic import BaseModel, ConfigDict, field_serializer

from app.dependencies import CurrentUserDep, DbSession
from app.enums import EditSource
from app.repository import sections as sections_repo
from app.repository.sections import HistoryCursor, ReportMeta
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


def parse_history_cursor(
    cursor: Annotated[str | None, Query()] = None,
) -> HistoryCursor | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        data = json.loads(raw)
        return HistoryCursor(
            ts=datetime.fromisoformat(data["ts"]),
            edit_id=int(data["id"]),
        )
    except (ValueError, KeyError, TypeError):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_cursor", "message": "Cursor is malformed"},
        ) from None


def _encode_cursor(c: HistoryCursor) -> str:
    payload = json.dumps(
        {"ts": c.ts.isoformat(), "id": c.edit_id}, separators=(",", ":")
    )
    return (
        base64.urlsafe_b64encode(payload.encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )


ViewAccess = Annotated[ReportMeta, Depends(require_view_access)]
EditAccess = Annotated[ReportMeta, Depends(require_edit_access)]
IfMatch = Annotated[int, Depends(require_if_match)]
HistoryCursorDep = Annotated[HistoryCursor | None, Depends(parse_history_cursor)]


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


class EditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_before: int
    version_after: int
    content_before: dict[str, Any]
    content_after: dict[str, Any]
    editor_user_id: int
    source: EditSource
    ts: datetime

    @field_serializer("ts")
    def _serialize_ts(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()


class HistoryResponse(BaseModel):
    edits: list[EditResponse]
    next_cursor: str | None


class RevertResponse(BaseModel):
    version: int
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


@router.get(
    "/{report_id}/sections/{section_key}/history",
    response_model=HistoryResponse,
)
async def read_section_history(
    meta: ViewAccess,
    section_key: Annotated[str, Path(min_length=1)],
    db: DbSession,
    cursor: HistoryCursorDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> HistoryResponse:
    try:
        page = await sections_service.read_history(
            db,
            meta=meta,
            section_key=section_key,
            limit=limit,
            cursor=cursor,
        )
    except sections_service.SectionsError as err:
        raise _http_error(err) from err
    return HistoryResponse(
        edits=[EditResponse.model_validate(e) for e in page.edits],
        next_cursor=_encode_cursor(page.next_cursor) if page.next_cursor else None,
    )


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


@router.post(
    "/{report_id}/sections/{section_key}/revert/{edit_id}",
    response_model=RevertResponse,
)
async def revert_section(
    meta: EditAccess,
    section_key: Annotated[str, Path(min_length=1)],
    edit_id: Annotated[int, Path(gt=0)],
    current_user: CurrentUserDep,
    db: DbSession,
) -> RevertResponse:
    try:
        section = await sections_service.revert_section(
            db,
            meta=meta,
            editor_user_id=current_user.user_id,
            section_key=section_key,
            target_edit_id=edit_id,
        )
    except sections_service.SectionsError as err:
        raise _http_error(err) from err
    return RevertResponse(version=section.version, content=section.content)
