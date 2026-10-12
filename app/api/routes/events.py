from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import error_responses
from app.db.models import JobRun
from app.db.session import get_db
from app.modules.ingestion.event_store import get_event_by_delivery_id
from app.schemas.jobs import EventOut

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/{delivery_id}", response_model=EventOut, responses=error_responses(404, 422))
def get_event(delivery_id: str, db: Session = Depends(get_db)):
  """One webhook delivery and the background jobs it started, with their status."""
  event = get_event_by_delivery_id(db, delivery_id)
  if event is None:
    raise HTTPException(status_code=404, detail="Event not found")

  jobs = db.scalars(select(JobRun).where(JobRun.event_id == event.id).order_by(JobRun.id)).all()
  return {
    "id": event.id,
    "github_delivery_id": event.github_delivery_id,
    "event_type": event.event_type,
    "action": event.action,
    "status": event.status,
    "error_message": event.error_message,
    "received_at": event.received_at,
    "processed_at": event.processed_at,
    "jobs": jobs,
  }
