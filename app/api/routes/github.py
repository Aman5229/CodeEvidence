import hashlib, hmac
from datetime import datetime
from fastapi import HTTPException, APIRouter, Request, Header, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.core.config import settings
from app.db.session import get_db
from app.db.models import GitHubEvent

router = APIRouter(prefix="/webhooks", tags=["github"])

def verify_signature(raw_body: bytes, signature_header: str | None) -> None:
  if not signature_header or not signature_header.startswith("sha256="):
    raise HTTPException(status_code=401, detail="Missing or malformed signature")

  expected = hmac.new(
    key=settings.github_webhook_secret.encode("utf-8"),
    msg=raw_body,
    digestmod=hashlib.sha256,
  ).hexdigest()

  provided = signature_header.removeprefix("sha256=")

  if not hmac.compare_digest(provided, expected):
    raise HTTPException(status_code=401, detail="Invalid singature")

@router.post("/github")
async def github_webhook(
  request: Request,
  x_github_delivery: str | None = Header(default=None),
  x_github_event: str | None = Header(default=None),
  x_hub_signature_256: str | None = Header(default=None),
  db_session: Session = Depends(get_db),
):

  if not x_github_delivery:
    raise HTTPException(status_code=400, detail="Missing X-GitHub-Delivery header")
  if not x_github_event:
    raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")

  raw_body = await request.body()
  verify_signature(raw_body, x_hub_signature_256)

  existing = db.execute(
    select(GitHubEvent).where(GitHubEvent.github_delivery_id == x_github_delivery)
  ).scalar_one_or_none()

  if existing is not None:
    return { "status": "duplicate_ignored", "delivery_id": x_github_delivery, "event": x_github_event }

  payload = await request.json()

  event = GitHubEvent(
    github_delivery_id=x_github_delivery,
    event_type=x_github_event,
    action=payload.get("action"),
    repository_id=None,
    payload=payload,
    status="received",
    received_at=datetime.now(timezone.utc),
  )

  db.add(event)
  db.commit()

  return { "status": "received", "delivery_id": x_github_delivery, "event": x_github_event }
