"""Risk scores stored by the worker (T58) and served by GET /pull-requests/{id}/risk (T59)."""

from sqlalchemy import func, select

import app.modules.risk.service as risk_service

from app.db.models import PullRequestFile, PullRequestRisk
from app.modules.ml.features import MODEL_FEATURES
from app.modules.ml.serving import RiskModel
from app.modules.risk.service import MIN_REPO_HISTORY, compute_risk, score_repository
from tests.integration.test_github_webhook import pr_payload, repo_payload, send_webhook
from tests.integration.test_pull_request_detail import START
from tests.integration.test_pull_requests_api import add_pull_request, add_repository


def add_file(db_session, pull_request, path: str, lines: int) -> None:
  db_session.add(
    PullRequestFile(
      pull_request_id=pull_request.id, path=path, status="modified", additions=lines,
      deletions=0, changes=lines, patch_truncated=False, is_stale=False, created_at=START,
    )
  )
  db_session.commit()


def repository_with_prs(db_session, sizes: list[int]):
  """A repository whose PRs each change one code file of the given size."""
  repository = add_repository(db_session)
  pull_requests = []
  for number, lines in enumerate(sizes, start=1):
    pull_request = add_pull_request(db_session, repository, number, day=number)
    add_file(db_session, pull_request, "app/module.py", lines)
    pull_requests.append(pull_request)
  return repository, pull_requests


def reason_codes(risk: PullRequestRisk) -> list[str]:
  return [reason["code"] for reason in risk.reasons]


# ---------- computed by the worker, served by the API ----------

def test_worker_scores_a_pr_after_syncing_its_files(client, worker):
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}
  send_webhook(client, "d-1", "pull_request", payload)
  worker.run()
  pull_request_id = client.get("/repositories/1/pull-requests").json()["items"][0]["id"]

  body = client.get(f"/pull-requests/{pull_request_id}/risk").json()

  # The fake GitHub returns app/main.py (+5 -1) and app/new_feature.py (+20): 26 lines, no tests.
  assert body["features"]["files_changed"] == 2
  assert body["features"]["lines_changed"] == 26
  assert body["features"]["test_file_ratio"] == 0.0
  assert body["features"]["size_percentile"] == 0.5  # a new repository has no size history
  assert (body["score"], body["level"]) == (10, "low")
  assert [reason["code"] for reason in body["reasons"]] == ["typical_change"]
  assert body["version"] == "rules-v1"
  assert body["model"] is None  # no trained model loaded: rule score only


def test_unknown_pull_request_is_404(client):
  response = client.get("/pull-requests/999/risk")

  assert response.status_code == 404
  assert response.json()["error"]["message"] == "Pull request not found"


def test_pr_not_scored_yet_is_404_with_a_clear_message(client, db_session):
  pull_request = add_pull_request(db_session, add_repository(db_session), 1)

  response = client.get(f"/pull-requests/{pull_request.id}/risk")

  assert response.status_code == 404
  assert "not computed yet" in response.json()["error"]["message"]


# ---------- compute_risk ----------

def test_scoring_again_replaces_the_row(db_session):
  _, (pull_request,) = repository_with_prs(db_session, [40])

  compute_risk(db_session, pull_request.id)
  compute_risk(db_session, pull_request.id)

  assert db_session.scalar(select(func.count()).select_from(PullRequestRisk)) == 1


def test_size_is_judged_against_the_repository_once_it_has_history(db_session):
  sizes = [10] * MIN_REPO_HISTORY + [800]  # 20 small PRs, then a big one
  repository, pull_requests = repository_with_prs(db_session, sizes)
  for pull_request in pull_requests[:-1]:
    compute_risk(db_session, pull_request.id)

  risk = compute_risk(db_session, pull_requests[-1].id)

  assert risk.size_percentile == 1.0
  assert "very_large_for_repo" in reason_codes(risk)
  assert "many_lines" in reason_codes(risk)


def test_first_prs_of_a_repository_are_not_called_large_for_it(db_session):
  _, pull_requests = repository_with_prs(db_session, [5, 10, 400])

  risk = None
  for pull_request in pull_requests:
    risk = compute_risk(db_session, pull_request.id)

  assert risk.size_percentile == 0.5  # cold start: too little history to judge
  assert "very_large_for_repo" not in reason_codes(risk)


# ---------- score_repository (rescoring existing data) ----------

def test_rescoring_a_repository_uses_one_complete_baseline(db_session):
  sizes = list(range(10, 10 * (MIN_REPO_HISTORY + 6), 10))  # 25 PRs: 10, 20, ... 250 lines
  repository, pull_requests = repository_with_prs(db_session, sizes)

  scored = score_repository(db_session, repository.id)

  assert scored == len(sizes)
  smallest = db_session.get(PullRequestRisk, pull_requests[0].id)
  largest = db_session.get(PullRequestRisk, pull_requests[-1].id)
  assert smallest.size_percentile == 1 / len(sizes)
  assert largest.size_percentile == 1.0
  assert "very_large_for_repo" in reason_codes(largest)
  assert largest.score > smallest.score


# ---------- the trained model, served next to the rules ----------

class FixedEstimator:
  """Stands in for a trained model: always the same probability."""

  def predict_proba(self, rows):
    assert len(rows[0]) == len(MODEL_FEATURES)
    return [[0.2, 0.8]]


def test_model_prediction_is_stored_and_served_next_to_the_rule_score(client, db_session, monkeypatch):
  model = RiskModel(version="risk-model-test", threshold=0.6, estimator=FixedEstimator())
  monkeypatch.setattr(risk_service, "get_risk_model", lambda: model)
  _, (pull_request,) = repository_with_prs(db_session, [40])
  compute_risk(db_session, pull_request.id)

  body = client.get(f"/pull-requests/{pull_request.id}/risk").json()

  assert body["model"] == {"version": "risk-model-test", "probability": 0.8, "flagged": True}
  assert body["score"] == 10  # the rule score is unchanged
  risk = db_session.get(PullRequestRisk, pull_request.id)
  assert len(risk.model_inputs) == len(MODEL_FEATURES)  # logged for the drift check


def test_rescoring_skips_prs_whose_files_were_never_synced(db_session):
  repository, (synced,) = repository_with_prs(db_session, [40])
  never_synced = add_pull_request(db_session, repository, 99, day=99)

  assert score_repository(db_session, repository.id) == 1
  assert db_session.get(PullRequestRisk, synced.id) is not None
  assert db_session.get(PullRequestRisk, never_synced.id) is None
