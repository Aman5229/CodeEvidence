import pytest

from app.core.pagination import decode_cursor, encode_cursor


def test_cursor_round_trip():
  assert decode_cursor(encode_cursor([42])) == [42]


def test_decode_rejects_garbage():
  with pytest.raises(ValueError):
    decode_cursor("!!!")


def test_decode_rejects_non_list():
  with pytest.raises(ValueError):
    decode_cursor(encode_cursor({"a": 1}))