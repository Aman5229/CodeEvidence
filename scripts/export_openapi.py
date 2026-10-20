"""Write the API's OpenAPI spec to frontend/openapi.json; the dashboard's types are generated
from it (cd frontend && npm run gen:api). Re-run both after changing an endpoint or schema.

  python -m scripts.export_openapi
"""
import json
from pathlib import Path

from app.main import app

OUT = Path("frontend/openapi.json")


def main() -> None:
  OUT.write_text(json.dumps(app.openapi(), indent=2) + "\n")
  print(f"Wrote {OUT}")


if __name__ == "__main__":
  main()
