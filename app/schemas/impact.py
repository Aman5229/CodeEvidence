from pydantic import BaseModel


class ChangedSymbolOut(BaseModel):
  name: str
  kind: str  # function, method, class
  change: str  # added, modified, removed; changed when the repository is not indexed


class ChangedFileOut(BaseModel):
  path: str
  status: str
  additions: int
  deletions: int
  symbols: list[ChangedSymbolOut]


class DependentChunkOut(BaseModel):
  name: str | None
  kind: str
  start_line: int
  end_line: int
  uses: list[str]


class DependentFileOut(BaseModel):
  path: str
  is_test: bool
  uses: list[str]  # the changed names it mentions
  changed_files: list[str]  # the changed files that define them
  chunks: list[DependentChunkOut]


class ImpactOut(BaseModel):
  pull_request_id: int
  indexed: bool  # false: index the repository's code to find dependents
  changed: list[ChangedFileOut]
  dependents: list[DependentFileOut]  # most uses first
  truncated: bool  # more than shown
