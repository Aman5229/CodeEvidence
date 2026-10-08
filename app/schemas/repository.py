from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RepositoryOut(BaseModel):
  model_config = ConfigDict(from_attributes=True)

  id: int
  full_name: str
  owner: str
  default_branch: str
  html_url: str
  is_private: bool
  last_synced_at: datetime

class RepositoryStats(BaseModel):
  repository_id: int
  total_prs: int
  closed_prs: int
  merged_prs: int
  merge_rate: float | None
  bot_prs: int
  bot_share: float | None
  median_lines_changed: float | None
  median_hours_to_close: float | None
