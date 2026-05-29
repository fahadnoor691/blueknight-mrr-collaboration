from dataclasses import dataclass

from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.config import settings


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    org_id: int


def decode_token(token: str) -> CurrentUser:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": "JWT could not be validated"},
        )
    try:
        user_id = int(payload["sub"])
        org_id = int(payload["org_id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": "JWT missing required claims (sub, org_id)"},
        )
    return CurrentUser(user_id=user_id, org_id=org_id)
