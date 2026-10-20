from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.errors import error_responses
from app.db.models import Repository
from app.db.session import get_db
from app.modules.analytics import acceptance, compute_analytics
from app.schemas.analytics import AnalyticsOut

router = APIRouter(tags=["insights"])


@router.get("/analytics", response_model=AnalyticsOut, responses=error_responses(404, 422))
def analytics(
  repository_id: int | None = None,
  days: int = Query(default=90, ge=1, le=730),
  db: Session = Depends(get_db),
):
  """
  How useful the reviews are, over the last `days` days (one repository, or all): acceptance
  of findings by category, findings and votes per week, results per model and prompt, merge
  rate by risk level, where findings land, why findings were dropped, static analysis
  results, learnings and chat use.

  Findings are counted once, when the model raised them: not again in cached reviews or when
  an incremental review carries them over. `repeats_after_rejection` counts findings raised
  again after a 👎 on the same problem in the same repository.
  """
  if repository_id is not None and db.get(Repository, repository_id) is None:
    raise HTTPException(status_code=404, detail="Repository not found")
  result = asdict(compute_analytics(db, days=days, repository_id=repository_id))
  votes = result["votes"]
  return AnalyticsOut(**result, repository_id=repository_id, acceptance=acceptance(votes["useful"], votes["not_useful"]))
