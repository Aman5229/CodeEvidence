from app.modules.review.repo_config import RepoConfig


class RepoConfigOut(RepoConfig):
  """The review settings of a repository, as read from `.codeevidence.yaml` on its default branch."""

  source: str  # file: read from .codeevidence.yaml; default: no such file
  error: str | None  # why the file could not be used (the defaults were used instead)
  guideline_files: list[str]  # guideline files found and given to the reviewer
