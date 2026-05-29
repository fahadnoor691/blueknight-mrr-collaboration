from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, decode_token
from app.database import SessionLocal
from app.llm_client import InMemoryLLMClient, LLMClient


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing_token", "message": "Authorization bearer token required"},
        )
    token = authorization.split(" ", 1)[1]
    return decode_token(token)


_llm_client: LLMClient = InMemoryLLMClient()


def get_llm_client() -> LLMClient:
    return _llm_client


DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]
