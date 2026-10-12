from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.errors import error_responses
from app.core.config import settings
from app.db.session import get_db
from app.integrations.github.signature import is_valid_signature
from app.jobs import get_event_queue
from app.modules.ingestion.event_store import mark_event_failed
from app.modules.ingestion.service import STATUS_DUPLICATE, accept_github_event

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/github", status_code=202, responses=error_responses(400, 401, 422, 503))
async def github_webhook(
  request: Request,
  response: Response,
  x_github_delivery: str | None = Header(default=None),
  x_github_event: str | None = Header(default=None),
  x_hub_signature_256: str | None = Header(default=None),
  db: Session = Depends(get_db),
  enqueue: Callable[[int], None] = Depends(get_event_queue),
):
  """
  Verifies the HMAC signature, stores the raw event and queues it for processing.
  Returns 202 immediately; the worker does the rest. A repeated delivery returns 200.
  """
  if not x_github_delivery:
    raise HTTPException(status_code=400, detail="Missing X-GitHub-Delivery header")
  if not x_github_event:
    raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")

  raw_body = await request.body()
  if not is_valid_signature(raw_body, x_hub_signature_256, settings.github_webhook_secret):
    raise HTTPException(status_code=401, detail="Invalid signature")

  try:
    payload = await request.json()
  except ValueError as error:
    raise HTTPException(status_code=400, detail="Invalid JSON payload") from error

  event = accept_github_event(
    db, delivery_id=x_github_delivery, event_type=x_github_event, payload=payload
  )
  if event is None:
    response.status_code = 200
    return {"status": STATUS_DUPLICATE, "delivery_id": x_github_delivery}

  try:
    enqueue(event.id)  # after the commit, so the worker can already see the row
  except Exception as error:
    # Stored but not queued: mark it failed so GitHub's "Redeliver" can retry it.
    mark_event_failed(event, error)
    db.commit()
    raise HTTPException(status_code=503, detail="Event stored, but could not be queued") from error

  return {"status": "queued", "delivery_id": x_github_delivery, "event": x_github_event}
