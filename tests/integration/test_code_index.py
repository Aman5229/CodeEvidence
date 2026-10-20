"""Indexing a repository into pgvector, file contents by blob SHA, and hybrid retrieval."""

import asyncio

import pytest
from sqlalchemy import func, select

from app.db.models import CodeChunk, FileBlob
from app.modules.code.contents import get_file_text
from app.modules.code.embeddings import FakeEmbedder
from app.modules.code.filters import MAX_FILE_BYTES
from app.modules.code.indexing import index_repository
from app.modules.code.retrieval import retrieve
from tests.integration.test_pull_requests_api import add_repository

USERS = b'''def load_user(user_id):
    return db.query(User).get(user_id)


def delete_user(user_id):
    db.delete(load_user(user_id))
'''

BILLING = b'''class Invoice:
    def total(self):
        return sum(line.amount for line in self.lines)
'''


@pytest.fixture
def repository(db_session, fake_github):
  fake_github.tree = [
    {"path": "app/users.py", "type": "blob", "sha": "u1", "size": len(USERS)},
    {"path": "app/billing.py", "type": "blob", "sha": "b1", "size": len(BILLING)},
    {"path": "package-lock.json", "type": "blob", "sha": "l1", "size": 10},
    {"path": "docs/logo.png", "type": "blob", "sha": "p1", "size": 10},
  ]
  fake_github.blobs = {"u1": USERS, "b1": BILLING}
  return add_repository(db_session)


def run_index(db_session, fake_github, repository):
  return asyncio.run(index_repository(db_session, fake_github, FakeEmbedder(), repository.id))


def chunk_names(db_session) -> list[str]:
  return sorted(db_session.scalars(select(CodeChunk.name)).all())


def test_code_files_are_chunked_and_embedded(db_session, fake_github, repository):
  result = run_index(db_session, fake_github, repository)

  assert (result.indexed, result.skipped, result.chunks) == (2, 2, 3)
  assert chunk_names(db_session) == ["Invoice", "delete_user", "load_user"]
  chunk = db_session.scalars(select(CodeChunk).where(CodeChunk.name == "load_user")).one()
  assert (chunk.start_line, chunk.end_line, chunk.kind) == (1, 2, "function")
  assert len(chunk.embedding) == 384


def test_re_running_changes_nothing_and_fetches_nothing(db_session, fake_github, repository):
  run_index(db_session, fake_github, repository)
  fake_github.blob_calls.clear()

  result = run_index(db_session, fake_github, repository)

  assert (result.indexed, result.unchanged) == (0, 2)
  assert fake_github.blob_calls == []
  assert db_session.scalar(select(func.count()).select_from(CodeChunk)) == 3


def test_changed_and_deleted_files_are_updated(db_session, fake_github, repository):
  run_index(db_session, fake_github, repository)
  fake_github.tree = [{"path": "app/users.py", "type": "blob", "sha": "u2", "size": 30}]
  fake_github.blobs["u2"] = b"def load_user(user_id):\n    return cache[user_id]\n"

  result = run_index(db_session, fake_github, repository)

  assert (result.indexed, result.removed) == (1, 1)
  assert chunk_names(db_session) == ["load_user"]


def test_file_text_is_fetched_once_per_blob(db_session, fake_github, repository):
  fake_github.blobs["big"] = b"x" * (MAX_FILE_BYTES + 1)

  first = asyncio.run(get_file_text(db_session, fake_github, "octo/repo1", "u1"))
  again = asyncio.run(get_file_text(db_session, fake_github, "octo/repo1", "u1"))
  big = asyncio.run(get_file_text(db_session, fake_github, "octo/repo1", "big"))

  assert first == again == USERS.decode()
  assert fake_github.blob_calls == ["u1", "big"]
  assert big is None
  assert db_session.get(FileBlob, "big").skipped_reason == "too_large"


@pytest.mark.parametrize("mode", ["vector", "keyword", "hybrid"])
def test_retrieval_finds_the_related_function(db_session, fake_github, repository, mode):
  run_index(db_session, fake_github, repository)

  found = retrieve(db_session, FakeEmbedder(), repository.id, "+    user = load_user(request.user_id)", k=2, mode=mode)

  assert found[0].name in {"load_user", "delete_user"}
  assert "Invoice" not in [chunk.name for chunk in found[:1]]


def test_hybrid_says_which_search_found_each_chunk(db_session, fake_github, repository):
  run_index(db_session, fake_github, repository)

  found = retrieve(db_session, FakeEmbedder(), repository.id, "load_user user_id", k=3)

  assert set(found[0].found_by) == {"vector", "keyword"}


def test_index_endpoint_queues_a_job_that_the_worker_runs(client, db_session, fake_github, repository, worker):
  response = client.post(f"/repositories/{repository.id}/index")
  worker.run()

  assert response.status_code == 202
  assert worker.failures == []
  assert chunk_names(db_session) == ["Invoice", "delete_user", "load_user"]


def test_index_unknown_repository_is_404(client):
  assert client.post("/repositories/999/index").status_code == 404


def test_two_jobs_fetching_the_same_blob_at_once_do_not_crash(db_session, engine, fake_github, repository):
  from sqlalchemy.orm import Session as OrmSession

  from app.core.time_utils import utc_now

  original = fake_github.get_blob

  async def other_job_stores_it_first(repo_full_name, blob_sha):
    with OrmSession(engine) as other:  # another worker, another connection
      other.add(FileBlob(blob_sha=blob_sha, size_bytes=3, content="old", fetched_at=utc_now()))
      other.commit()
    return await original(repo_full_name, blob_sha)

  fake_github.get_blob = other_job_stores_it_first

  text = asyncio.run(get_file_text(db_session, fake_github, "octo/repo1", "u1"))
  db_session.commit()

  assert text == USERS.decode()  # this job's copy is used now
  assert db_session.scalar(select(func.count()).select_from(FileBlob)) == 1  # and one row is stored
