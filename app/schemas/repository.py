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