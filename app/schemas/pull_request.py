from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field


class PullRequestFileOut(BaseModel):
  model_config = ConfigDict(from_attributes=True)

  path: str
  previous_path: str | None
  status: str
  additions: int
  deletions: int
  changes: int

class PullRequestFileWithPatch(PullRequestFileOut):
  patch: str | None

class PullRequestTotals(BaseModel):
  files_changed: int
  additions: int
  deletions: int
  lines_changed: int

class PullRequestSummary(BaseModel):
  model_config = ConfigDict(from_attributes=True)

  id: int
  number: int
  title: str
  author_login: str | None
  status: str
  created_at: datetime
  closed_at: datetime | None
  merged_at: datetime | None

  @computed_field
  @property
  def is_bot(self) -> bool:
    return self.author_login is not None and self.author_login.endswith("[bot]")

  @computed_field
  @property
  def is_merged(self) -> bool:
    return self.merged_at is not None

class PullRequestDetail(PullRequestSummary):
  body: str | None
  base_branch: str
  head_branch: str
  head_sha: str
  updated_at: datetime
  files: list[PullRequestFileOut]

  @computed_field
  @property
  def totals(self) -> PullRequestTotals:
    additions = sum(f.additions for f in self.files)
    deletions = sum(f.deletions for f in self.files)
    return PullRequestTotals(
      files_changed=len(self.files),
      additions=additions,
      deletions=deletions,
      lines_changed=additions + deletions,
    )

class PullRequestDetailWithPatch(PullRequestDetail):
  files: list[PullRequestFileWithPatch]