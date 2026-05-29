from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, field_serializer

from app.dependencies import CurrentUserDep, DbSession
from app.services import sections as sections_service

router = APIRouter(prefix="/reports", tags=["sections"])


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


def _http_error(err: sections_service.SectionsError) -> HTTPException:
    return HTTPException(
        status_code=err.status,
        detail={"error": err.code, "message": err.message},
    )


@router.get("/{report_id}", response_model=ReportResponse)
async def read_report(
    report_id: Annotated[int, Path(gt=0)],
    current_user: CurrentUserDep,
    db: DbSession,
) -> ReportResponse:
    try:
        report = await sections_service.read_report(
            db,
            actor_user_id=current_user.user_id,
            report_id=report_id,
        )
    except sections_service.SectionsError as err:
        raise _http_error(err) from err
    return ReportResponse.model_validate(report)


@router.get(
    "/{report_id}/sections/{section_key}",
    response_model=SectionResponse,
)
async def read_section(
    report_id: Annotated[int, Path(gt=0)],
    section_key: Annotated[str, Path(min_length=1)],
    current_user: CurrentUserDep,
    db: DbSession,
    response: Response,
) -> SectionResponse:
    try:
        section = await sections_service.read_section(
            db,
            actor_user_id=current_user.user_id,
            report_id=report_id,
            section_key=section_key,
        )
    except sections_service.SectionsError as err:
        raise _http_error(err) from err
    response.headers["ETag"] = f'"{section.version}"'
    return SectionResponse.model_validate(section)
