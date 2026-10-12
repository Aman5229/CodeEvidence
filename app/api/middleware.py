"""Per-request observability: a request id, one access log line and a latency measurement."""

import logging
import re
import time
import uuid

from fastapi import Request

from app.core.logs import request_id_var
from app.core.metrics import HTTP_REQUEST_DURATION

logger = logging.getLogger("app.access")

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")  # a caller's id must not inject log text


async def observe_requests(request: Request, call_next):
  incoming = request.headers.get(REQUEST_ID_HEADER, "")
  request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
  token = request_id_var.set(request_id)
  started = time.perf_counter()
  status = 500
  try:
    response = await call_next(request)
    status = response.status_code
    response.headers[REQUEST_ID_HEADER] = request_id
    return response
  finally:
    duration = time.perf_counter() - started
    route = request.scope.get("route")
    route_path = route.path if route else "unmatched"  # templates, never raw ids: few label values
    HTTP_REQUEST_DURATION.labels(request.method, route_path, str(status)).observe(duration)
    logger.info(
      "%s %s %s",
      request.method,
      request.url.path,
      status,
      extra={"status": status, "route": route_path, "duration_ms": round(duration * 1000, 1)},
    )
    request_id_var.reset(token)
