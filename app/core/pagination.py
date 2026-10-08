import base64
import json


def encode_cursor(values: list) -> str:
  raw = json.dumps(values).encode()
  return base64.urlsafe_b64encode(raw).decode()

def decode_cursor(cursor: str) -> list:
  try:
    values = json.loads(base64.urlsafe_b64decode(cursor.encode()))
  except ValueError as error:
    raise ValueError("Invalid cursor") from error
  if not isinstance(values, list):
    raise ValueError("Invalid cursor")
  return values