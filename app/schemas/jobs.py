from pydantic import BaseModel

class ProcessEventPayload(BaseModel):
  event_id: int

class SyncPullRequestFilesPayload(BaseModel):
  pull_request_id: int