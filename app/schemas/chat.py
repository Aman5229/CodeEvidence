from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CitationOut(BaseModel):
  id: str  # the evidence id the answer cites, e.g. H2
  kind: str
  path: str | None
  start_line: int | None
  end_line: int | None


class ChatMessageOut(BaseModel):
  model_config = ConfigDict(from_attributes=True)

  id: int
  role: str  # user, assistant
  content: str  # Markdown; answers cite evidence as [H2]
  citations: list[CitationOut]
  source: str  # dashboard, github
  github_user: str | None
  model: str | None
  cost_usd: float | None
  latency_ms: int | None
  created_at: datetime


class ChatQuestionIn(BaseModel):
  question: str = Field(min_length=1, max_length=2000)


class ChatTokenEvent(BaseModel):
  """Event "token": the next piece of the answer."""

  text: str


class ChatDoneEvent(BaseModel):
  """Event "done": the stored question and answer."""

  question: ChatMessageOut
  answer: ChatMessageOut
  unknown_citations: list[str]  # ids the model cited that are not in the evidence (not shown)


class ChatErrorEvent(BaseModel):
  """Event "error": no answer (over budget, or the model failed). Nothing is stored."""

  message: str
