from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_text_embedder
from app.api.errors import error_responses
from app.db.models import Learning, Repository
from app.db.session import get_db
from app.modules.code.embeddings import Embedder
from app.modules.review.learnings import create_learning, is_blanket_rule, update_learning
from app.schemas.learning import LearningIn, LearningOut, LearningUpdate

router = APIRouter(tags=["learnings"])

BLANKET_RULE_ERROR = "A learning must not turn off a whole category of findings (e.g. 'ignore all security issues')"


@router.get(
  "/repositories/{repository_id}/learnings",
  response_model=list[LearningOut],
  responses=error_responses(404, 422),
)
def list_learnings(repository_id: int, db: Session = Depends(get_db)):
  """The repository's learnings, newest first. Enabled ones are given to every review whose
  files they match; disabled ones (including those proposed on GitHub) are not."""
  if db.get(Repository, repository_id) is None:
    raise HTTPException(status_code=404, detail="Repository not found")
  return db.scalars(
    select(Learning).where(Learning.repository_id == repository_id).order_by(Learning.created_at.desc(), Learning.id.desc())
  ).all()


@router.post(
  "/repositories/{repository_id}/learnings",
  status_code=201,
  response_model=LearningOut,
  responses=error_responses(404, 422, 503),
)
def add_learning(
  repository_id: int, body: LearningIn, db: Session = Depends(get_db), embedder: Embedder = Depends(get_text_embedder)
):
  """Write a rule for future reviews of this repository; enabled at once."""
  if db.get(Repository, repository_id) is None:
    raise HTTPException(status_code=404, detail="Repository not found")
  text = " ".join(body.text.split())
  if is_blanket_rule(text):
    raise HTTPException(status_code=422, detail=BLANKET_RULE_ERROR)
  learning = create_learning(
    db, embedder, repository_id=repository_id, text=text, path_glob=body.path_glob, source="manual", enabled=True
  )
  db.commit()
  return learning


@router.patch("/learnings/{learning_id}", response_model=LearningOut, responses=error_responses(404, 422, 503))
def change_learning(
  learning_id: int, body: LearningUpdate, db: Session = Depends(get_db), embedder: Embedder = Depends(get_text_embedder)
):
  """Edit a learning, or enable it (approve one proposed on GitHub) or disable it."""
  learning = db.get(Learning, learning_id)
  if learning is None:
    raise HTTPException(status_code=404, detail="Learning not found")
  text = " ".join(body.text.split()) if body.text is not None else None
  if text is not None and is_blanket_rule(text):
    raise HTTPException(status_code=422, detail=BLANKET_RULE_ERROR)
  update_learning(
    db, embedder, learning, text=text, path_glob=body.path_glob, enabled=body.enabled,
    path_glob_given="path_glob" in body.model_fields_set,
  )
  db.commit()
  return learning


@router.delete("/learnings/{learning_id}", status_code=204, responses=error_responses(404, 422))
def delete_learning(learning_id: int, db: Session = Depends(get_db)) -> Response:
  learning = db.get(Learning, learning_id)
  if learning is None:
    raise HTTPException(status_code=404, detail="Learning not found")
  db.delete(learning)
  db.commit()
  return Response(status_code=204)
