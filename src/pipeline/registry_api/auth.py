# pattern: Imperative Shell

import hashlib
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from pydantic import BaseModel

from pipeline.registry_api.db import DbDep, get_token_by_hash


_bearer_scheme = HTTPBearer(auto_error=False)

ROLE_HIERARCHY: dict[str, int] = {
    "read": 0,
    "write": 1,
    "admin": 2,
}


class TokenInfo(BaseModel):
    """Authenticated token metadata returned by require_auth."""

    username: str
    role: Literal["admin", "write", "read"]


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: DbDep = ...,
) -> TokenInfo:
    """
    FastAPI dependency that validates bearer tokens.

    Extracts the token from the Authorization header, hashes it with SHA-256,
    looks up the hash in the tokens table, and returns TokenInfo on success.

    Raises:
        HTTPException 401: Missing/invalid/revoked token
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="missing authentication credentials")

    token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    token_row = get_token_by_hash(db, token_hash)

    if token_row is None:
        raise HTTPException(status_code=401, detail="invalid authentication credentials")

    if token_row["revoked_at"] is not None:
        raise HTTPException(status_code=401, detail="token has been revoked")

    return TokenInfo(username=token_row["username"], role=token_row["role"])


AuthDep = Annotated[TokenInfo, Depends(require_auth)]


def require_role(minimum: str) -> Any:
    """
    Dependency factory that enforces minimum role level.

    Usage: Depends(require_role("write"))

    Role hierarchy: admin > write > read

    Note: returns FastAPI's opaque ``Depends(...)`` value. Annotated as ``Any``
    (per design #19 AC1.5) because exposing FastAPI's private ``Depends`` type
    would leak internal coupling. Callers use the returned value as a default
    parameter value in route signatures.
    """

    def _check_role(token: AuthDep) -> TokenInfo:
        if ROLE_HIERARCHY[token.role] < ROLE_HIERARCHY[minimum]:
            raise HTTPException(
                status_code=403,
                detail=f"insufficient permissions: requires {minimum} role",
            )
        return token

    return Depends(_check_role)
