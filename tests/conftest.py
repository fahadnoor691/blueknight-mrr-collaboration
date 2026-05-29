from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from dotenv import load_dotenv
load_dotenv()

os.environ["DATABASE_URL"] = os.environ.get(
    "DATABASE_URL",
    os.environ.get("DATABASE_URL", ""),
)

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_ALGORITHM", "HS256")

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings
from app.dependencies import get_db, get_llm_client
from app.enums import SharePermission
from app.llm_client import InMemoryLLMClient
from app.main import app as fastapi_app
from app.models import MarketResearchReport, ReportSection, ReportShare, User

test_engine = create_async_engine(
    settings.database_url, poolclass=NullPool, future=True
)
TestSessionLocal = async_sessionmaker(
    test_engine, expire_on_commit=False, class_=AsyncSession
)


async def _override_get_db() -> AsyncIterator[AsyncSession]:
    async with TestSessionLocal() as session:
        yield session


fastapi_app.dependency_overrides[get_db] = _override_get_db


_TRUNCATE_SQL = text(
    "TRUNCATE report_section_edits, report_sections, report_shares, "
    "market_research_reports, users RESTART IDENTITY CASCADE"
)


def _ensure_test_database_exists() -> None:
    async def _go() -> None:
        base, dbname = settings.database_url.rsplit("/", 1)
        admin_url = f"{base}/postgres"
        admin_engine = create_async_engine(
            admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool
        )
        try:
            async with admin_engine.connect() as conn:
                exists = (
                    await conn.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :n"),
                        {"n": dbname},
                    )
                ).scalar()
                if exists is None:
                    await conn.execute(text(f'CREATE DATABASE "{dbname}"'))
        finally:
            await admin_engine.dispose()

    asyncio.run(_go())


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations() -> None:
    _ensure_test_database_exists()
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture(autouse=True)
async def _truncate() -> None:
    async with test_engine.begin() as conn:
        await conn.execute(_TRUNCATE_SQL)


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with TestSessionLocal() as session:
        yield session


@pytest.fixture
def app():
    return fastapi_app


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
def make_token() -> Callable[..., str]:
    def _make(user_id: int, org_id: int = 1) -> str:
        return jwt.encode(
            {"sub": str(user_id), "org_id": org_id},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

    return _make


@pytest.fixture
def llm_stub(app) -> InMemoryLLMClient:
    stub = InMemoryLLMClient()
    app.dependency_overrides[get_llm_client] = lambda: stub
    yield stub
    app.dependency_overrides.pop(get_llm_client, None)


@dataclass(frozen=True)
class UserInfo:
    id: int
    org_id: int
    email: str
    token: str
    auth: dict[str, str]


@dataclass(frozen=True)
class SeedData:
    owner: UserInfo
    editor: UserInfo
    viewer: UserInfo
    outsider_same_org: UserInfo
    outsider_other_org: UserInfo
    report_id: int
    overview_key: str
    financials_key: str
    editor_share_id: int
    viewer_share_id: int


@pytest_asyncio.fixture
async def seed(db: AsyncSession, make_token) -> SeedData:
    org_a, org_b = 1, 2

    owner = User(org_id=org_a, email="owner@example.com")
    editor = User(org_id=org_a, email="editor@example.com")
    viewer = User(org_id=org_a, email="viewer@example.com")
    outsider_a = User(org_id=org_a, email="outsider-a@example.com")
    outsider_b = User(org_id=org_b, email="outsider-b@example.com")
    db.add_all([owner, editor, viewer, outsider_a, outsider_b])
    await db.flush()

    report = MarketResearchReport(
        user_id=owner.id,
        company_name="Acme",
        company_url="https://acme.example.com",
        sections={},
    )
    db.add(report)
    await db.flush()

    overview = ReportSection(
        report_id=report.id,
        section_key="overview",
        content={"text": "initial overview"},
        version=1,
        updated_by_user_id=owner.id,
    )
    financials = ReportSection(
        report_id=report.id,
        section_key="financials",
        content={"text": "initial financials"},
        version=1,
        updated_by_user_id=owner.id,
    )
    edit_share = ReportShare(
        report_id=report.id,
        target_user_id=editor.id,
        permission=SharePermission.edit,
        granted_by_user_id=owner.id,
    )
    view_share = ReportShare(
        report_id=report.id,
        target_user_id=viewer.id,
        permission=SharePermission.view,
        granted_by_user_id=owner.id,
    )
    db.add_all([overview, financials, edit_share, view_share])
    await db.commit()

    def info(u: User) -> UserInfo:
        token = make_token(u.id, u.org_id)
        return UserInfo(
            id=u.id,
            org_id=u.org_id,
            email=u.email,
            token=token,
            auth={"Authorization": f"Bearer {token}"},
        )

    return SeedData(
        owner=info(owner),
        editor=info(editor),
        viewer=info(viewer),
        outsider_same_org=info(outsider_a),
        outsider_other_org=info(outsider_b),
        report_id=report.id,
        overview_key="overview",
        financials_key="financials",
        editor_share_id=edit_share.id,
        viewer_share_id=view_share.id,
    )
