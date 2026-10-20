"""AI review end to end with a fake LLM: job, storage, cache, budget, API, feedback, publishing."""

import asyncio
import json

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import FindingFeedback, Review, ReviewFinding
from app.modules.review.feedback import collect_reactions
from app.modules.review.publishing import publish_review
from tests.integration.test_github_webhook import pr_payload, repo_payload, send_webhook

PATCH = """@@ -1,3 +1,4 @@
 def handler(request):
-    return load(request.args["id"])
+    item_id = request.args["id"]
+    return eval(item_id)"""

FINDING = {
  "path": "app/handler.py", "line": 3, "severity": "high", "category": "security",
  "claim": "eval runs the id from the request as code: anyone can run Python on the server.",
  "quote": "return eval(item_id)", "evidence": ["H1", "S1"], "suggestion": "Use int(item_id).", "confidence": 0.9,
}
INVENTED = {**FINDING, "quote": "os.system(item_id)", "claim": "Runs a shell command built from the request."}


def answers(*findings) -> str:
  return json.dumps({"findings": list(findings)})


@pytest.fixture
def pull_request_id(client, fake_github, worker):
  """A PR synced through the webhook, whose single file adds an eval."""
  fake_github.files = [
    {"filename": "app/handler.py", "status": "modified", "additions": 2, "deletions": 1, "changes": 3, "patch": PATCH, "sha": "h1"}
  ]
  fake_github.blobs["h1"] = b'def handler(request):\n    item_id = request.args["id"]\n    return eval(item_id)\n'
  send_webhook(client, "d-1", "pull_request", {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()})
  worker.run()
  return client.get("/repositories/1/pull-requests").json()["items"][0]["id"]


def run_review(client, worker, pull_request_id) -> dict:
  assert client.post(f"/pull-requests/{pull_request_id}/review").status_code == 202
  worker.run()
  assert worker.failures == []
  return client.get(f"/pull-requests/{pull_request_id}/review").json()


def test_review_returns_verified_findings_with_their_evidence(client, worker, fake_llm, pull_request_id):
  fake_llm.answers = [answers(FINDING, INVENTED), "Handler now evaluates the request id in app/handler.py."]

  body = run_review(client, worker, pull_request_id)

  assert body["status"] == "completed"
  assert body["summary"] == "Handler now evaluates the request id in app/handler.py."
  assert [(f["rank"], f["line"], f["quote"]) for f in body["findings"]] == [(1, 3, "return eval(item_id)")]
  assert body["dropped_findings"] == 1  # the invented os.system finding
  assert [item["id"] for item in body["findings"][0]["evidence"]] == ["H1", "S1"]
  # findings, summary, diagram (the fake answers the diagram with the summary: not a diagram)
  assert body["llm_calls"] == 3 and body["cost_usd"] > 0 and not body["cached"]
  assert body["diagram"] is None and body["mode"] == "full"


def test_the_enclosing_function_is_part_of_the_evidence(client, worker, fake_llm, pull_request_id):
  run_review(client, worker, pull_request_id)

  system, user = fake_llm.calls[0]
  assert 'kind="function" path="app/handler.py" lines="1-3"' in user


def test_same_diff_again_is_a_cache_hit_with_no_llm_call(client, db_session, worker, fake_llm, pull_request_id):
  fake_llm.answers = [answers(FINDING), "Summary of handler.py."]
  run_review(client, worker, pull_request_id)
  calls = len(fake_llm.calls)

  body = run_review(client, worker, pull_request_id)

  assert len(fake_llm.calls) == calls
  assert body["cached"] and body["llm_calls"] == 0 and body["cost_usd"] == 0
  assert [f["quote"] for f in body["findings"]] == ["return eval(item_id)"]
  assert db_session.scalar(select(func.count()).select_from(Review)) == 2


def test_an_unreadable_answer_is_not_reused(client, worker, fake_llm, pull_request_id):
  fake_llm.answers = ["not json", "still not json", "Summary of handler.py.", "NONE"]
  first = run_review(client, worker, pull_request_id)
  fake_llm.answers = [answers(FINDING), "Summary of handler.py.", "NONE"]
  fake_llm.calls.clear()

  again = run_review(client, worker, pull_request_id)

  assert first["findings"] == [] and not again["cached"]
  assert [f["quote"] for f in again["findings"]] == ["return eval(item_id)"]


def test_budget_exceeded_stops_cleanly_and_is_not_cached(client, worker, fake_llm, pull_request_id, monkeypatch):
  monkeypatch.setattr(settings, "review_budget_usd", 0.000001)

  body = run_review(client, worker, pull_request_id)

  assert body["status"] == "budget_exceeded"
  assert body["findings"] == [] and fake_llm.calls == []


def test_review_404s(client, db_session):
  from tests.integration.test_pull_requests_api import add_pull_request, add_repository

  pull_request = add_pull_request(db_session, add_repository(db_session), 1)

  assert client.get("/pull-requests/999/review").json()["error"]["message"] == "Pull request not found"
  assert "No review yet" in client.get(f"/pull-requests/{pull_request.id}/review").json()["error"]["message"]
  assert client.post("/pull-requests/999/review").status_code == 404


def test_reviews_run_automatically_when_enabled(client, db_session, fake_github, worker, monkeypatch):
  monkeypatch.setattr(settings, "review_on_sync", True)
  fake_github.blobs = {"abc123": b"def main():\n    pass\n", "def456": b"def feature():\n    pass\n"}
  send_webhook(client, "d-9", "pull_request", {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()})

  worker.run()

  assert worker.failures == []
  assert db_session.scalar(select(func.count()).select_from(Review)) == 1


# ---------- feedback ----------

def test_dashboard_feedback_is_counted(client, worker, fake_llm, pull_request_id):
  fake_llm.answers = [answers(FINDING), "Summary of handler.py."]
  finding_id = run_review(client, worker, pull_request_id)["findings"][0]["id"]

  saved = client.post(f"/findings/{finding_id}/feedback", json={"verdict": "useful"})
  client.post(f"/findings/{finding_id}/feedback", json={"verdict": "not_useful"})

  assert saved.status_code == 201
  feedback = client.get(f"/pull-requests/{pull_request_id}/review").json()["findings"][0]["feedback"]
  assert feedback == {"useful": 1, "not_useful": 1, "replies": 0}
  assert client.post("/findings/999/feedback", json={"verdict": "useful"}).status_code == 404
  assert client.post(f"/findings/{finding_id}/feedback", json={"verdict": "great"}).status_code == 422


# ---------- publishing to GitHub ----------

@pytest.fixture
def published(client, db_session, fake_github, worker, fake_llm, pull_request_id, monkeypatch):
  """A review posted to the (fake) sandbox repository."""
  monkeypatch.setattr(settings, "publish_repositories", "octo/demo")
  fake_llm.answers = [answers(FINDING), "Summary of handler.py."]
  run_review(client, worker, pull_request_id)  # completed -> publish job queued and run
  return db_session.scalars(select(Review)).one()


def test_review_is_posted_as_inline_comments(published, fake_github):
  (posted,) = fake_github.reviews_posted

  assert posted["commit_id"] == published.head_sha
  assert [(c["path"], c["line"], c["side"]) for c in posted["comments"]] == [("app/handler.py", 3, "RIGHT")]
  assert published.published_at is not None and published.github_review_id == 501


def test_publishing_again_posts_nothing(db_session, fake_github, published):
  published.published_at = None  # as if the job crashed before recording it
  db_session.commit()

  posted_now = asyncio.run(publish_review(db_session, fake_github, published.id))

  assert posted_now == 0
  assert len(fake_github.reviews_posted) == 1


def test_only_allowed_repositories_are_written_to(client, db_session, fake_github, worker, fake_llm, pull_request_id, monkeypatch):
  monkeypatch.setattr(settings, "publish_repositories", "someone/else")
  fake_llm.answers = [answers(FINDING), "Summary of handler.py."]

  run_review(client, worker, pull_request_id)

  assert fake_github.reviews_posted == []


def test_reactions_and_replies_become_feedback(client, db_session, fake_github, worker, published):
  finding = db_session.scalars(select(ReviewFinding).where(ReviewFinding.rank == 1)).one()
  fake_github.reactions[finding.github_comment_id] = [
    {"id": 1, "content": "+1", "user": {"login": "maintainer"}},
    {"id": 2, "content": "eyes", "user": {"login": "maintainer"}},  # carries no verdict
  ]
  reply = {
    "action": "created",
    "repository": repo_payload(),
    "comment": {"id": 77, "in_reply_to_id": finding.github_comment_id, "body": "Good catch", "user": {"login": "maintainer"}},
  }

  assert asyncio.run(collect_reactions(db_session, fake_github, published)) == 1
  assert asyncio.run(collect_reactions(db_session, fake_github, published)) == 0  # recorded once
  send_webhook(client, "d-reply", "pull_request_review_comment", reply)
  worker.run()

  feedback = db_session.scalars(select(FindingFeedback).order_by(FindingFeedback.id)).all()
  assert [(f.source, f.verdict, f.body) for f in feedback] == [
    ("github_reaction", "useful", None),
    ("github_reply", None, "Good catch"),
  ]
