from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.errors import error_responses
from app.db.models import PullRequest, PullRequestRisk
from app.db.session import get_db
from app.schemas.risk import ModelScoreOut, RiskFeaturesOut, RiskOut

router = APIRouter(tags=["pull-requests"])


@router.get(
  "/pull-requests/{pull_request_id}/risk",
  response_model=RiskOut,
  responses=error_responses(404, 422),
)
def get_risk(pull_request_id: int, db: Session = Depends(get_db)):
  """
  The PR's risk score (0 to 100), its level and the reasons behind it, plus the features it
  was computed from. Computed by the worker once the PR's files are synced.

  `model` is the trained model's prediction, shown next to the rule score. It is null when
  no model is loaded; the rule score is always there.
  """
  risk = db.get(PullRequestRisk, pull_request_id)
  if risk is None:
    if db.get(PullRequest, pull_request_id) is None:
      raise HTTPException(status_code=404, detail="Pull request not found")
    raise HTTPException(
      status_code=404, detail="Risk not computed yet: it is computed after the PR's files are synced"
    )

  return RiskOut(
    pull_request_id=risk.pull_request_id,
    score=risk.score,
    level=risk.level,
    reasons=risk.reasons,
    features=RiskFeaturesOut.model_validate(risk, from_attributes=True),
    model=ModelScoreOut(
      version=risk.model_version, probability=risk.model_probability, flagged=risk.model_flagged
    )
    if risk.model_version is not None
    else None,
    version=risk.version,
    computed_at=risk.computed_at,
  )
