"""Index a repository's code (default branch) for retrieval: chunk, embed, store.

Safe to re-run: a file whose blob SHA (and embedding model) is unchanged since the last run
is skipped, so a second run only fetches and embeds what changed. Files deleted from the repository lose their
chunks. Each file is committed on its own, so an interrupted run keeps its progress.
"""

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.time_utils import utc_now
from app.db.models import CodeChunk, Repository
from app.integrations.github.client import GitHubClient
from app.modules.code.chunking import Chunk, chunk_file
from app.modules.code.contents import get_file_text
from app.modules.code.embeddings import Embedder
from app.modules.code.filters import MAX_FILE_BYTES, detect_language, looks_generated, skip_reason
from app.modules.code.tokens import code_tokens

MAX_INDEXED_FILES = 3000


@dataclass
class IndexResult:
  indexed: int = 0  # files chunked and embedded in this run
  unchanged: int = 0  # same blob SHA as last time: skipped
  skipped: int = 0  # not code, too large, binary or generated
  removed: int = 0  # gone from the repository: chunks deleted
  chunks: int = 0


def embedding_text(chunk: Chunk) -> str:
  """What gets embedded: the path and name say where the code lives, which helps matching."""
  return f"{chunk.path}\n{chunk.name or ''}\n{chunk.content}"


async def index_repository(db: Session, github: GitHubClient, embedder: Embedder, repository_id: int) -> IndexResult:
  repository = db.get(Repository, repository_id)
  if repository is None:
    raise ValueError(f"Repository {repository_id} does not exist")
  result = IndexResult()

  tree = await github.get_tree(repository.full_name, repository.default_branch)
  wanted = {}
  for entry in tree:
    if skip_reason(entry["path"]) or not detect_language(entry["path"]) or entry.get("size", 0) > MAX_FILE_BYTES:
      result.skipped += 1
    elif len(wanted) < MAX_INDEXED_FILES:
      wanted[entry["path"]] = entry["sha"]

  indexed = {
    path: (blob_sha, model)
    for path, blob_sha, model in db.execute(
      select(CodeChunk.path, CodeChunk.blob_sha, CodeChunk.embedding_model)
      .where(CodeChunk.repository_id == repository_id)
      .distinct()
    )
  }
  gone = [path for path in indexed if path not in wanted]
  if gone:
    db.execute(delete(CodeChunk).where(CodeChunk.repository_id == repository_id, CodeChunk.path.in_(gone)))
    db.commit()
    result.removed = len(gone)

  for path, blob_sha in wanted.items():
    if indexed.get(path) == (blob_sha, embedder.model_name):  # a new model means new vectors
      result.unchanged += 1
      continue
    content = await get_file_text(db, github, repository.full_name, blob_sha)
    chunks = chunk_file(path, content, detect_language(path)) if content and not looks_generated(content) else []
    db.execute(delete(CodeChunk).where(CodeChunk.repository_id == repository_id, CodeChunk.path == path))
    if not chunks:
      db.commit()
      result.skipped += 1
      continue
    vectors = embedder.embed([embedding_text(chunk) for chunk in chunks])
    now = utc_now()
    for chunk, vector in zip(chunks, vectors, strict=True):
      db.add(
        CodeChunk(
          repository_id=repository_id,
          path=path,
          blob_sha=blob_sha,
          language=chunk.language,
          kind=chunk.kind,
          name=chunk.name,
          start_line=chunk.start_line,
          end_line=chunk.end_line,
          content=chunk.content,
          embedding=vector,
          embedding_model=embedder.model_name,
          search_text=" ".join(code_tokens(f"{path} {chunk.name or ''} {chunk.content}")),
          created_at=now,
        )
      )
    db.commit()
    result.indexed += 1
    result.chunks += len(chunks)
  return result
