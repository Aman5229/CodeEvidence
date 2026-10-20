from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_model, get_text_embedder
from app.api.errors import error_responses, json_error_responses
from app.core.config import settings
from app.db.models import ChatMessage, PullRequest
from app.db.session import get_db
from app.modules.code.embeddings import Embedder
from app.modules.review.chat import ChatAnswer, chat_bundle, history, save_exchange, stream_answer
from app.modules.review.llm import BudgetExceeded, CostMeter, LLMError, LLMProvider
from app.schemas.chat import ChatDoneEvent, ChatErrorEvent, ChatMessageOut, ChatQuestionIn, ChatTokenEvent

router = APIRouter(tags=["chat"])


def existing_pull_request(pull_request_id: int, db: Session = Depends(get_db)) -> PullRequest:
  pull_request = db.get(PullRequest, pull_request_id)
  if pull_request is None:
    raise HTTPException(status_code=404, detail="Pull request not found")
  return pull_request


@router.get(
  "/pull-requests/{pull_request_id}/chat",
  response_model=list[ChatMessageOut],
  responses=error_responses(404, 422),
)
def chat_history(pull_request: PullRequest = Depends(existing_pull_request), db: Session = Depends(get_db)):
  """The conversation about this PR, oldest first: questions asked in the dashboard or with
  @codeevidence on GitHub, and the answers with the evidence they cite."""
  return db.scalars(
    select(ChatMessage).where(ChatMessage.pull_request_id == pull_request.id).order_by(ChatMessage.id)
  ).all()


@router.post(
  "/pull-requests/{pull_request_id}/chat",
  response_class=EventSourceResponse,
  responses=json_error_responses(401, 404, 422, 429, 503),
)
def ask(
  body: ChatQuestionIn,
  pull_request: PullRequest = Depends(existing_pull_request),
  db: Session = Depends(get_db),
  llm: LLMProvider = Depends(get_model),
  embedder: Embedder = Depends(get_text_embedder),
) -> Iterator[ServerSentEvent]:
  """
  Ask a question about the PR. The answer streams as server-sent events:
  - `token`: `{"text": "..."}`, the next piece of the answer;
  - `done`: `{"question", "answer", "unknown_citations"}`, both messages as stored;
  - `error`: `{"message": "..."}`, no answer (over budget, or the model failed); nothing is stored.

  The answer uses the PR's latest review evidence (or its diff) plus code found for the
  question, and cites it as [H2], [Q1]... Earlier messages give follow-ups their context.
  """
  question = body.question.strip()
  earlier = history(db, pull_request.id)
  bundle = chat_bundle(db, embedder, pull_request, question, settings.chat_token_budget)
  meter = CostMeter(llm, settings.chat_budget_usd)
  try:
    final: ChatAnswer | None = None
    for chunk in stream_answer(meter, bundle, earlier, question):
      if isinstance(chunk, ChatAnswer):
        final = chunk
      else:
        yield ServerSentEvent(event="token", data=ChatTokenEvent(text=chunk))
    asked, answered = save_exchange(db, pull_request.id, question, final, bundle, source="dashboard", model=llm.model)
    db.commit()
    yield ServerSentEvent(
      event="done",
      data=ChatDoneEvent(
        question=ChatMessageOut.model_validate(asked),
        answer=ChatMessageOut.model_validate(answered),
        unknown_citations=final.unknown_citations,
      ),
    )
  except BudgetExceeded:
    message = "Answering would go over the budget for one answer. Try a narrower question."
    yield ServerSentEvent(event="error", data=ChatErrorEvent(message=message))
  except LLMError as error:
    yield ServerSentEvent(event="error", data=ChatErrorEvent(message=f"The model could not answer: {error}"))
