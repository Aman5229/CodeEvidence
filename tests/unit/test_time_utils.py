from datetime import datetime, timezone

from app.core.time_utils import parse_iso_timestamp, utc_now


def test_parses_github_timestamp_with_z_suffix():
  result = parse_iso_timestamp("2024-06-01T09:30:00Z")
  assert result == datetime(2024, 6, 1, 9, 30, 0, tzinfo=timezone.utc)


def test_parsed_timestamp_is_timezone_aware():
  result = parse_iso_timestamp("2024-06-01T09:30:00Z")
  assert result.tzinfo is not None


def test_none_returns_none():
  assert parse_iso_timestamp(None) is None


def test_utc_now_is_in_utc():
  assert utc_now().tzinfo == timezone.utc
