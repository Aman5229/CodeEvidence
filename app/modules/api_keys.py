"""API keys: created once, shown once, stored only as a SHA-256 hash.

A plain (unsalted) SHA-256 is enough here because keys are 32 random bytes, not passwords:
there is nothing to guess or look up in a dictionary. Lookup is by the hash, so the stored
hash is never compared with attacker-chosen input byte by byte.
"""

import hashlib
import hmac
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time_utils import utc_now
from app.db.models import ApiKey

KEY_PREFIX = "ce_"


def hash_key(key: str) -> str:
  return hashlib.sha256(key.encode()).hexdigest()


def create_api_key(db: Session, name: str) -> tuple[ApiKey, str]:
  """Returns the stored row and the key itself. The key cannot be recovered later."""
  key = KEY_PREFIX + secrets.token_urlsafe(32)
  api_key = ApiKey(name=name, key_prefix=key[:10], key_hash=hash_key(key), created_at=utc_now())
  db.add(api_key)
  db.commit()
  return api_key, key


def find_active_key(db: Session, key: str) -> ApiKey | None:
  key_hash = hash_key(key)
  api_key = db.scalars(select(ApiKey).where(ApiKey.key_hash == key_hash)).one_or_none()
  if api_key is None or api_key.revoked_at is not None:
    return None
  if not hmac.compare_digest(api_key.key_hash, key_hash):  # constant-time, belt and braces
    return None
  return api_key


def revoke_api_key(db: Session, api_key: ApiKey) -> None:
  api_key.revoked_at = utc_now()
  db.commit()
