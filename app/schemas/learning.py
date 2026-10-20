from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.review.learnings import MAX_LEARNING_CHARS, MIN_LEARNING_CHARS


class LearningOut(BaseModel):
  model_config = ConfigDict(from_attributes=True)

  id: int
  repository_id: int
  text: str
  path_glob: str | None  # where it applies, e.g. src/api/**; null: everywhere
  source: str  # manual, dashboard (a 👎 with a reason), github (a reply or "remember")
  source_finding_id: int | None
  enabled: bool  # disabled: not used in reviews (learnings from GitHub wait for approval)
  times_applied: int
  last_applied_at: datetime | None
  created_at: datetime
  updated_at: datetime


class LearningIn(BaseModel):
  text: str = Field(min_length=MIN_LEARNING_CHARS, max_length=MAX_LEARNING_CHARS)
  path_glob: str | None = Field(default=None, max_length=255)


class LearningUpdate(BaseModel):
  """Only the fields sent are changed; send "path_glob": null to apply it everywhere."""

  text: str | None = Field(default=None, min_length=MIN_LEARNING_CHARS, max_length=MAX_LEARNING_CHARS)
  path_glob: str | None = Field(default=None, max_length=255)
  enabled: bool | None = None
