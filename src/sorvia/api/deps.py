"""Shared services and FastAPI dependencies."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sorvia.config import Settings
from sorvia.db import Database
from sorvia.executor import ScopedExecutor
from sorvia.nl2sql.embeddings import Embedder
from sorvia.nl2sql.pipeline import AskService
from sorvia.security import Principal, decode_token


class RateLimiter:
    """Sliding-window limiter per key. In-process; use a shared store when scaling out."""

    def __init__(self, limit: int, window_s: float = 60.0) -> None:
        self.limit = limit
        self.window = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


@dataclass
class Services:
    settings: Settings
    db: Database
    ask: AskService
    embedder: Embedder
    executor: ScopedExecutor
    limiter: RateLimiter


def services(request: Request) -> Services:
    svc: Services = request.app.state.services
    return svc


_bearer = HTTPBearer(auto_error=False)


def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    svc = services(request)
    try:
        return decode_token(credentials.credentials, svc.settings.jwt_secret.get_secret_value())
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"}) from exc


def require_roles(*roles: str) -> Callable[[Principal], Principal]:
    def checker(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return principal

    return checker


ServicesDep = Annotated[Services, Depends(services)]
PrincipalDep = Annotated[Principal, Depends(current_principal)]
AdminDep = Annotated[Principal, Depends(require_roles("admin"))]
ManagerDep = Annotated[Principal, Depends(require_roles("admin", "manager"))]
