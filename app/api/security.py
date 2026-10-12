"""Who may call the read API, and how often."""

import math

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import take_token
from app.db.models import ApiKey
from app.db.redis import get_redis
from app.db.session import get_db
from app.modules.api_keys import find_active_key

api_key_header = APIKeyHeader(
  name="X-API-Key",
  auto_error=False,  # we raise our own 401 in the shared error format
  description="Create one with: python -m scripts.create_api_key <name>",
)


def require_api_key(
  key: str | None = Security(api_key_header), db: Session = Depends(get_db)
) -> ApiKey:
  if not key:
    raise HTTPException(status_code=401, detail="Missing API key: send it in the X-API-Key header")
  api_key = find_active_key(db, key)
  if api_key is None:
    raise HTTPException(status_code=401, detail="Invalid or revoked API key")
  return api_key


def enforce_rate_limit(
  api_key: ApiKey = Depends(require_api_key), cache: Redis = Depends(get_redis)
) -> ApiKey:
  allowed, retry_after = take_token(
    cache, f"ratelimit:{api_key.id}", settings.rate_limit_capacity, settings.rate_limit_per_second
  )
  if not allowed:
    raise HTTPException(
      status_code=429,
      detail="Rate limit exceeded",
      headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
    )
  return api_key
