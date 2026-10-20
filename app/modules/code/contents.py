"""File contents from GitHub, fetched once per blob SHA and cached in the database.

A blob SHA is a hash of the file's content: the same SHA is always the same text, so a
cached copy never goes stale. Large and binary files are recorded as skipped.
"""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.time_utils import utc_now
from app.db.models import FileBlob
from app.integrations.github.client import GitHubClient
from app.modules.code.filters import MAX_FILE_BYTES


async def get_file_text(db: Session, github: GitHubClient, repo_full_name: str, blob_sha: str) -> str | None:
  """The file's text, or None when it is too large or not text."""
  blob = db.get(FileBlob, blob_sha)
  if blob is not None:
    return blob.content
  raw = await github.get_blob(repo_full_name, blob_sha)
  content, skipped_reason = None, None
  if len(raw) > MAX_FILE_BYTES:
    skipped_reason = "too_large"
  elif b"\0" in raw[:8000]:
    skipped_reason = "binary"
  else:
    try:
      content = raw.decode("utf-8")
    except UnicodeDecodeError:
      skipped_reason = "binary"
  # Two jobs (an index and a review, or two indexes) can fetch the same blob at the same
  # time. The content is identical, so whoever stores it second just keeps the first copy.
  db.execute(
    insert(FileBlob)
    .values(blob_sha=blob_sha, size_bytes=len(raw), content=content, skipped_reason=skipped_reason, fetched_at=utc_now())
    .on_conflict_do_nothing(index_elements=["blob_sha"])
  )
  return content
