"""Endpoints behind the dashboard: overview, PR insights, review history, index status."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.models import CodeChunk, FindingFeedback, PullRequestRisk, Review, ReviewFinding
from tests.integration.test_pull_request_detail import START
from tests.integration.test_pull_requests_api import add_pull_request, add_repository

EVIDENCE = [
  {"id": "H1", "kind": "hunk", "path": "app/x.py", "start_line": 1, "end_line": 3, "text": "+x = eval(y)", "new_lines": [1]},
  {"id": "S1", "kind": "signal", "path": "app/x.py", "start_line": 1, "end_line": 1, "text": "eval", "new_lines": []},
]


def add_risk(db_session, pull_request, score: int, level: str) -> None:
  db_session.add(
    PullRequestRisk(
      pull_request_id=pull_request.id, repository_id=pull_request.repository_id, files_changed=1,
      lines_changed=10, log_lines_changed=2.4, test_file_ratio=0.0, docs_only=False, is_bot=False,
      size_percentile=0.5, score=score, level=level, reasons=[], version="rules-v1", computed_at=START,
    )
  )
  db_session.commit()


def add_review(db_session, pull_request, *, shown=("high",), dropped=1, cached=False, minutes=0, cost=0.01) -> Review:
  review = Review(
    pull_request_id=pull_request.id, head_sha="b" * 40, status="completed", prompt_version="review_v1",
    model="fake-llm", cache_key="k" * 64, cached=cached, summary="Adds eval.", llm_calls=0 if cached else 2,
    input_tokens=100, output_tokens=20, cost_usd=0.0 if cached else cost, latency_ms=900, evidence=EVIDENCE,
    created_at=START + timedelta(minutes=minutes),
  )
  findings = [
    ReviewFinding(
      path="app/x.py", line=1, severity=severity, category="security", claim="eval runs input as code.",
      quote="x = eval(y)", suggestion=None, confidence=0.9, evidence=["H1", "S1"], status="kept",
      drop_reason=None, rank=rank, finding_key=f"{rank:032d}",
    )
    for rank, severity in enumerate(shown, start=1)
  ]
  findings += [
    ReviewFinding(
      path="app/x.py", line=9, severity="low", category="bug", claim="Something not in the diff.",
      quote="nope", suggestion=None, confidence=0.6, evidence=["H1"], status="dropped",
      drop_reason="quote_not_found", rank=None, finding_key=f"d{index:031d}",
    )
    for index in range(dropped)
  ]
  review.findings = findings
  db_session.add(review)
  db_session.commit()
  return review


@pytest.fixture
def prs(db_session):
  repository = add_repository(db_session)
  return [add_pull_request(db_session, repository, number, day=number) for number in (1, 2, 3)]


# ---------- overview ----------

def test_overview_of_an_empty_database(client):
  body = client.get("/overview").json()

  assert (body["repositories"], body["pull_requests"], body["reviews"]) == (0, 0, 0)
  assert body["risk_levels"] == {"low": 0, "medium": 0, "high": 0}
  assert body["recent_reviews"] == [] and body["riskiest"] == []


def test_overview_counts_and_lists(client, db_session, prs):
  add_risk(db_session, prs[0], 70, "high")
  add_risk(db_session, prs[1], 10, "low")
  review = add_review(db_session, prs[0], shown=("high", "medium"), dropped=1)
  add_review(db_session, prs[0], shown=("high", "medium"), dropped=1, cached=True, minutes=5)  # repeats the first
  finding_id = db_session.scalar(select(ReviewFinding.id).where(ReviewFinding.review_id == review.id, ReviewFinding.rank == 1))
  db_session.add(FindingFeedback(finding_id=finding_id, source="dashboard", verdict="useful", created_at=START))
  db_session.commit()

  body = client.get("/overview").json()

  assert (body["pull_requests"], body["reviewed_pull_requests"], body["reviews"]) == (3, 1, 2)
  assert (body["findings_shown"], body["findings_dropped"]) == (2, 1)  # the cached copy is not counted
  assert (body["feedback_useful"], body["feedback_not_useful"]) == (1, 0)
  assert body["review_cost_usd"] == 0.01
  assert body["risk_levels"] == {"low": 1, "medium": 0, "high": 1}
  assert [r["score"] for r in body["riskiest"]] == [70, 10]
  assert [r["findings_shown"] for r in body["recent_reviews"]] == [2, 2]
  assert body["recent_reviews"][0]["repository"] == "octo/repo1"


# ---------- PR insights ----------

def test_insights_give_risk_and_latest_review_per_pr(client, db_session, prs):
  add_risk(db_session, prs[0], 65, "high")
  add_review(db_session, prs[0], shown=("low",), minutes=0)
  add_review(db_session, prs[0], shown=("high", "high", "medium"), minutes=10)  # the latest one counts

  response = client.get("/pull-requests/insights", params={"ids": [prs[0].id, prs[1].id, 999]})

  assert response.status_code == 200  # not swallowed by /pull-requests/{id}
  first, second = response.json()
  assert first == {
    "pull_request_id": prs[0].id, "risk_score": 65, "risk_level": "high", "model_probability": None,
    "review_status": "completed", "findings_shown": 3, "findings_high": 2,
  }
  assert (second["risk_score"], second["review_status"], second["findings_shown"]) == (None, None, 0)


def test_insights_need_ids_and_cap_them(client):
  assert client.get("/pull-requests/insights").status_code == 422
  assert client.get("/pull-requests/insights", params={"ids": list(range(1, 102))}).status_code == 422


# ---------- review history and evidence ----------

def test_review_history_newest_first_with_counts(client, db_session, prs):
  older = add_review(db_session, prs[0], shown=("high",), dropped=2, minutes=0)
  newer = add_review(db_session, prs[0], shown=(), dropped=0, cached=True, minutes=5)

  runs = client.get(f"/pull-requests/{prs[0].id}/reviews").json()

  assert [run["id"] for run in runs] == [newer.id, older.id]
  assert [(run["findings_shown"], run["findings_dropped"], run["cached"]) for run in runs] == [(0, 0, True), (1, 2, False)]
  assert client.get("/pull-requests/999/reviews").status_code == 404
  assert client.get(f"/pull-requests/{prs[1].id}/reviews").json() == []


def test_review_includes_every_evidence_item(client, db_session, prs):
  add_review(db_session, prs[0])

  body = client.get(f"/pull-requests/{prs[0].id}/review").json()

  assert [item["id"] for item in body["evidence"]] == ["H1", "S1"]


def test_pull_request_list_includes_the_repository_id(client, prs):
  item = client.get(f"/repositories/{prs[0].repository_id}/pull-requests").json()["items"][0]

  assert item["repository_id"] == prs[0].repository_id


# ---------- index status ----------

def test_index_status(client, db_session, prs):
  repository_id = prs[0].repository_id
  for path, name in [("a.py", "f"), ("a.py", "g"), ("b.py", "h")]:
    db_session.add(
      CodeChunk(
        repository_id=repository_id, path=path, blob_sha="s", language="python", kind="function", name=name,
        start_line=1, end_line=2, content="def f(): pass", embedding=[0.1] * 384, embedding_model="fake-hashing-384",
        search_text="def f pass", created_at=START,
      )
    )
  db_session.commit()

  body = client.get(f"/repositories/{repository_id}/index").json()

  assert (body["files"], body["chunks"], body["embedding_model"]) == (2, 3, "fake-hashing-384")
  assert client.get("/repositories/999/index").status_code == 404
