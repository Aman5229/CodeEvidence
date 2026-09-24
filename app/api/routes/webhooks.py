from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.integrations.github.client import GitHubClient, get_github_client
from app.integrations.github.signature import is_valid_signature
from app.modules.ingestion.event_store import STATUS_FAILED
from app.modules.ingestion.service import STATUS_DUPLICATE, process_github_event

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/github")
async def github_webhook(
  request: Request,
  x_github_delivery: str | None = Header(default=None),
  x_github_event: str | None = Header(default=None),
  x_hub_signature_256: str | None = Header(default=None),
  db: Session = Depends(get_db),
  github: GitHubClient = Depends(get_github_client),
):
  if not x_github_delivery:
    raise HTTPException(status_code=400, detail="Missing X-GitHub-Delivery header")
  if not x_github_event:
    raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")

  raw_body = await request.body()
  if not is_valid_signature(raw_body, x_hub_signature_256, settings.github_webhook_secret):
    raise HTTPException(status_code=401, detail="Invalid signature")

  try:
    payload = await request.json()
  except ValueError:
    raise HTTPException(status_code=400, detail="Invalid JSON payload")

  status = await process_github_event(
    db,
    github,
    delivery_id=x_github_delivery,
    event_type=x_github_event,
    payload=payload,
  )

  if status == STATUS_FAILED:
    # The event IS stored (status=failed). A 500 makes GitHub show this delivery
    # as failed, so it can be retried with GitHub's "Redeliver" button.
    raise HTTPException(status_code=500, detail="Event stored, but processing failed")

  response_status = STATUS_DUPLICATE if status == STATUS_DUPLICATE else "received"
  return {"status": response_status, "delivery_id": x_github_delivery, "event": x_github_event}
