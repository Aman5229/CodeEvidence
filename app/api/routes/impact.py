import asyncio
from dataclasses import asdict

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.errors import error_responses
from app.db.models import PullRequest
from app.db.session import get_db
from app.integrations.github.client import GitHubClient, get_github_client
from app.modules.impact import compute_impact
from app.schemas.impact import ImpactOut

router = APIRouter(tags=["pull-requests"])


@router.get(
  "/pull-requests/{pull_request_id}/impact",
  response_model=ImpactOut,
  responses=error_responses(404, 422, 503),
)
def get_impact(
  pull_request_id: int, db: Session = Depends(get_db), github: GitHubClient = Depends(get_github_client)
):
  """
  Blast radius: the functions and classes the PR adds, changes or deletes, and the other
  code in the repository that uses them (from the code index of the default branch).

  Python and JavaScript are parsed; for other languages only definitions on added lines are
  found. Without an index (`indexed` false), dependents are empty: queue one with
  POST /repositories/{id}/index. File contents are read from GitHub once, then cached.
  """
  pull_request = db.get(PullRequest, pull_request_id)
  if pull_request is None:
    raise HTTPException(status_code=404, detail="Pull request not found")
  try:
    impact = asyncio.run(compute_impact(db, github, pull_request))
  except httpx.HTTPError as error:
    raise HTTPException(status_code=503, detail="Could not read the changed files from GitHub") from error
  db.commit()  # keeps the file contents read from GitHub
  return ImpactOut(pull_request_id=pull_request.id, **asdict(impact))
