"""/docs must describe the error shape the API really returns."""

from app.main import app

ERROR_REF = "#/components/schemas/ErrorResponse"


def operations():
  for path, methods in app.openapi()["paths"].items():
    for method, operation in methods.items():
      yield f"{method.upper()} {path}", operation


def test_every_documented_error_uses_the_shared_shape():
  for name, operation in operations():
    for status, response in operation["responses"].items():
      if int(status) >= 400:
        schema = response["content"]["application/json"]["schema"]
        assert schema == {"$ref": ERROR_REF}, f"{name} {status}"


def test_fastapi_default_validation_schema_is_gone():
  assert "HTTPValidationError" not in app.openapi()["components"]["schemas"]


def test_endpoints_with_ids_document_404():
  for name, operation in operations():
    if "{" in name and "webhooks" not in name:
      assert "404" in operation["responses"], name
