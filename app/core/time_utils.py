from datetime import datetime, timezone


def utc_now() -> datetime:
  """Current time as a timezone-aware UTC datetime."""
  return datetime.now(timezone.utc)


def parse_iso_timestamp(value: str | None) -> datetime | None:
  """Convert an ISO-8601 string like '2024-06-01T09:30:00Z' into a datetime.

  Returns None when the value is missing (e.g. an open PR has no merged_at).
  The 'Z' suffix is replaced because Python 3.10's fromisoformat() does not
  understand it.
  """
  if value is None:
    return None
  return datetime.fromisoformat(value.replace("Z", "+00:00"))
