"""Create an API key for the read API. The key is printed once and cannot be shown again.

Run from the project root:
  python -m scripts.create_api_key "my laptop"
"""
import argparse

from app.db.session import SessionLocal
from app.modules.api_keys import create_api_key


def main() -> None:
  parser = argparse.ArgumentParser(description="Create a read API key.")
  parser.add_argument("name", help="who or what will use the key")
  args = parser.parse_args()

  with SessionLocal() as db:  # print inside: the row's attributes reload through the session
    api_key, key = create_api_key(db, args.name)
    print(f"Created API key {api_key.key_prefix}... for {args.name!r} (id {api_key.id}).")
  print(f"Key (shown once, store it now): {key}")
  print('Use it as a header:  curl -H "X-API-Key: <key>" http://localhost:8000/repositories')


if __name__ == "__main__":
  main()
