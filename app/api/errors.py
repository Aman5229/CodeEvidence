import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.errors import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)

# Machine-readable code for each HTTP status. Clients branch on these,
# so once published they must not change.
ERROR_CODES = {
  400: "bad_request",
  401: "unauthorized",
  403: "forbidden",
  404: "not_found",
  405: "method_not_allowed",
  409: "conflict",
  422: "validation_error",
  429: "rate_limited",
  500: "internal_error",
}

# Text shown next to each error status in /docs.
ERROR_DESCRIPTIONS = {
  400: "Bad request, e.g. an invalid cursor or a missing header",
  401: "The webhook signature does not match",
  404: "The resource does not exist",
  422: "A parameter has the wrong type or value",
  500: "Unexpected server error",
}


def error_responses(*status_codes: int) -> dict[int, dict]:
  """OpenAPI `responses` entries that document errors in the shared shape."""
  return {
    code: {"model": ErrorResponse, "description": ERROR_DESCRIPTIONS[code]}
    for code in status_codes
  }


def error_response(
  status_code: int, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
  body = ErrorResponse(
    error=ErrorDetail(code=ERROR_CODES.get(status_code, "error"), message=message)
  )
  return JSONResponse(status_code=status_code, content=body.model_dump(), headers=headers)


async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
  return error_response(exc.status_code, str(exc.detail), headers=exc.headers)


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
  problems = [
    f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
    for error in exc.errors()
  ]
  return error_response(422, "; ".join(problems))


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
  logger.exception("Unhandled error on %s %s", request.method, request.url.path)
  return error_response(500, "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
  app.add_exception_handler(StarletteHTTPException, handle_http_exception)
  app.add_exception_handler(RequestValidationError, handle_validation_error)
  app.add_exception_handler(Exception, handle_unexpected_error)
