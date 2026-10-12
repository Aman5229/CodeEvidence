"""JSON logs, one object per line, with correlation ids on every line.

The ids live in context variables: set once (per request, per job) and readable by any code
running in that request or job, including library loggers. A webhook's request id travels
in the job message, so the worker's log lines carry the same id as the request that queued
the work: one id traces a webhook through the API and the worker.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
delivery_id_var: ContextVar[str | None] = ContextVar("delivery_id", default=None)
job_id_var: ContextVar[int | None] = ContextVar("job_id", default=None)

CONTEXT_FIELDS = {"request_id": request_id_var, "delivery_id": delivery_id_var, "job_id": job_id_var}

# Attributes every LogRecord has; anything else on a record came from `extra={...}`.
_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
  "message", "asctime", *CONTEXT_FIELDS,
}

_base_factory = logging.getLogRecordFactory()


def _record_with_context(*args, **kwargs) -> logging.LogRecord:
  record = _base_factory(*args, **kwargs)
  for name, var in CONTEXT_FIELDS.items():
    setattr(record, name, var.get())
  return record


class JsonFormatter(logging.Formatter):
  def format(self, record: logging.LogRecord) -> str:
    entry = {
      "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
      "level": record.levelname,
      "logger": record.name,
      "msg": record.getMessage(),
    }
    for name in CONTEXT_FIELDS:
      value = getattr(record, name, None)
      if value is not None:
        entry[name] = value
    for key, value in record.__dict__.items():
      if key not in _STANDARD_ATTRS and not key.startswith("_"):
        entry[key] = value  # fields passed with extra={...}
    if record.exc_info:
      entry["exception"] = self.formatException(record.exc_info)
    return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
  """Send every log line, ours and libraries', as JSON to stdout."""
  logging.setLogRecordFactory(_record_with_context)
  handler = logging.StreamHandler(sys.stdout)
  handler.setFormatter(JsonFormatter())
  root = logging.getLogger()
  root.handlers = [handler]
  root.setLevel(level)
  for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):  # use our handler, not theirs
    logging.getLogger(name).handlers = []
    logging.getLogger(name).propagate = True
