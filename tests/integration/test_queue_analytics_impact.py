"""The review queue (priority, effort, suggested reviewers), analytics and the impact view."""

import asyncio

import pytest

from app.db.models import PullRequestFile, PullRequestRisk, Repository
from app.modules.code.embeddings import FakeEmbedder
from app.modules.code.indexing import index_repository
from tests.integration.helpers import (
  FINDING,
  HANDLER_BLOB,
  HANDLER_PATCH,
  file_entry,
  review,
  scripted,
  sync_pull_request,
)
from tests.integration.test_pull_requests_api import add_pull_request, add_repository

INVENTED = {**FINDING, "quote": "os.system(item_id)", "claim": "Runs a shell command built from the request."}


def add_files(db_session, pull_request, *files: tuple[str, int]) -> None:
  for path, lines in files:
    db_session.add(PullRequestFile(
      pull_request_id=pull_request.id, path=path, status="modified", additions=lines, deletions=0, changes=lines,
      created_at=pull_request.created_at,
    ))
  db_session.commit()


def add_risk(db_session, pull_request, score: int, level: str, probability: float | None = None) -> None:
  db_session.add(PullRequestRisk(
    pull_request_id=pull_request.id, repository_id=pull_request.repository_id, files_changed=1, lines_changed=10,
    log_lines_changed=2.4, test_file_ratio=0.0, docs_only=False, is_bot=False, size_percentile=0.5, score=score,
    level=level, reasons=[], version="test", model_probability=probability, computed_at=pull_request.created_at,
  ))
  db_session.commit()


# ---------- review queue ----------

@pytest.fixture
def queue(db_session):
  repository = add_repository(db_session)
  history = [  # merged before the open PRs: who knows which files
    (1, "carol", ["app/billing.py"]),
    (2, "dave", ["app/billing.py", "app/tax.py"]),
    (3, "dependabot[bot]", ["app/billing.py"]),  # bots are not suggested
    (4, "erin", ["lib/old.py"]),
  ]
  for number, author, paths in history:
    add_files(db_session, add_pull_request(db_session, repository, number, author=author, merged=True, day=number), *[(p, 5) for p in paths])
  unmerged = add_pull_request(db_session, repository, 5, author="frank", day=4)  # closed without merging
  add_files(db_session, unmerged, ("app/billing.py", 5))

  risky = add_pull_request(db_session, repository, 10, author="alice", status="open", day=5)
  add_files(db_session, risky, ("app/billing.py", 200))
  add_risk(db_session, risky, 85, "high", probability=0.8)
  small = add_pull_request(db_session, repository, 11, author="bob", status="open", day=6)
  add_files(db_session, small, ("docs/readme.md", 5))
  add_risk(db_session, small, 20, "low")
  unscored = add_pull_request(db_session, repository, 12, author="alice", status="open", day=7)
  add_files(db_session, unscored, ("lib/new.py", 30))
  return repository


def test_open_prs_come_in_priority_order_with_effort_and_reviewers(client, queue):
  body = client.get("/review-queue").json()
  items = body["items"]

  assert [(item["number"], item["band"]) for item in items] == [(10, "P1"), (11, "P2"), (12, "P3")]
  assert (body["total"], body["p1"], body["p2"], body["p3"], body["not_reviewed"]) == (3, 1, 1, 1, 3)
  assert body["total_minutes"] == 30 + 5 + 15
  risky, small, unscored = items
  assert risky["effort"] == {"level": 3, "minutes": 30}
  assert risky["reasons"][:2] == ["risk 85 (high)", "model: 80% chance of rejection"]
  assert [r["login"] for r in risky["suggested_reviewers"]] == ["dave", "carol"]  # the author, bots and unmerged PRs left out
  assert small["suggested_reviewers"] == []
  assert unscored["risk_score"] is None and unscored["reasons"][0] == "risk not scored yet"
  assert [r["login"] for r in unscored["suggested_reviewers"]] == ["erin"]  # same folder, lib/
  assert risky["priority"] > small["priority"] > unscored["priority"]


def test_the_queue_can_be_limited_and_filtered(client, queue):
  limited = client.get("/review-queue", params={"limit": 1}).json()
  assert [item["number"] for item in limited["items"]] == [10]
  assert limited["total"] == 3  # the totals still count every open PR
  assert len(client.get("/review-queue", params={"repository_id": queue.id}).json()["items"]) == 3
  assert client.get("/review-queue", params={"repository_id": 99}).status_code == 404


# ---------- analytics ----------

def test_analytics_count_findings_once_and_votes_when_given(client, db_session, fake_github, fake_llm, worker):
  pull_request_id = sync_pull_request(client, fake_github, worker, [file_entry("app/handler.py", HANDLER_PATCH, "h1")], {"h1": HANDLER_BLOB})
  fake_llm.answers = scripted(findings=[FINDING, INVENTED], chat="It evals [H1].")
  finding_id = review(client, worker, pull_request_id)["findings"][0]["id"]
  review(client, worker, pull_request_id)  # cached: counted as a review, its findings are not
  client.post(f"/findings/{finding_id}/feedback", json={"verdict": "useful"})
  client.post(f"/findings/{finding_id}/feedback", json={"verdict": "not_useful"})
  fake_github.repo_files = {".codeevidence.yaml": b"profile: assertive\n"}  # a new input: the model runs again
  review(client, worker, pull_request_id)  # raises the same finding after the 👎: a repeat
  client.post("/repositories/1/learnings", json={"text": "Ids are validated by middleware."})
  client.post(f"/pull-requests/{pull_request_id}/chat", json={"question": "Is it safe?"})
  repository = db_session.get(Repository, 1)
  add_risk(db_session, add_pull_request(db_session, repository, 20, merged=True), 10, "low")
  add_risk(db_session, add_pull_request(db_session, repository, 21), 90, "high")

  body = client.get("/analytics").json()

  assert (body["reviews"], body["reviews_cached"]) == (3, 1)
  assert (body["findings_proposed"], body["findings_dropped"], body["findings_shown"]) == (4, 2, 2)
  assert body["votes"] == {"useful": 1, "not_useful": 1} and body["acceptance"] == 0.5
  security = next(c for c in body["categories"] if c["category"] == "security")
  assert (security["shown"], security["useful"], security["not_useful"], security["acceptance"]) == (2, 1, 1, 0.5)
  assert body["repeats_after_rejection"] == 1
  assert body["drop_reasons"] == [{"reason": "quote_not_found", "count": 2}]
  assert body["directories"] == [{"directory": "app", "findings": 2, "high": 2}]
  (model,) = body["models"]
  assert (model["model"], model["prompt_version"], model["reviews"], model["cached"]) == ("fake-llm", "review_v2", 3, 1)
  assert (body["learnings_total"], body["learnings_enabled"], body["chat_questions"]) == (1, 1, 1)
  outcomes = {o["level"]: (o["closed"], o["merged"], o["merge_rate"]) for o in body["risk_outcomes"]}
  assert outcomes == {"low": (1, 1, 1.0), "medium": (0, 0, None), "high": (1, 0, 0.0)}
  assert sum(week["reviews"] for week in body["weeks"]) == 3


def test_analytics_filters(client, queue):
  assert client.get("/analytics", params={"repository_id": queue.id, "days": 7}).json()["reviews"] == 0
  assert client.get("/analytics", params={"repository_id": 99}).status_code == 404
  assert client.get("/analytics", params={"days": 0}).status_code == 422


# ---------- impact ----------

DEFAULT_BRANCH = {
  "app/invoices.py": b"def load_invoice(invoice_id):\n    return db.get(invoice_id)\n\n\ndef total_due(invoice):\n"
                     b"    return sum(line.amount for line in invoice.lines)\n",
  "app/routes.py": b"def show_invoice(request):\n    invoice = load_invoice(request.id)\n    return render(invoice)\n",
  "tests/test_invoices.py": b"def test_load_invoice():\n    assert load_invoice(1).id == 1\n",
  "app/reports.py": b"def monthly_report(invoices):\n    return [total_due(i) for i in invoices]\n",
  "app/templates.py": b"def load_invoice_template():\n    return 'x'\n",  # a longer name: not a use
}
INVOICES_PATCH = """@@ -1,2 +1,3 @@
 def load_invoice(invoice_id):
-    return db.get(invoice_id)
+    invoice = db.get(invoice_id)
+    return invoice or None"""
INVOICES_HEAD = (
  b"def load_invoice(invoice_id):\n    invoice = db.get(invoice_id)\n    return invoice or None\n\n\n"
  b"def total_due(invoice):\n    return sum(line.amount for line in invoice.lines)\n"
)
PAYMENTS_PATCH = """@@ -0,0 +1,2 @@
+def refund_payment(payment):
+    return payment.refund()"""


@pytest.fixture
def changed_invoices(client, fake_github, worker):
  return sync_pull_request(
    client, fake_github, worker,
    [file_entry("app/invoices.py", INVOICES_PATCH, "i2"), file_entry("app/payments.py", PAYMENTS_PATCH, "p2", "added")],
    {"i2": INVOICES_HEAD, "p2": b"def refund_payment(payment):\n    return payment.refund()\n"},
  )


def index_default_branch(db_session, fake_github) -> None:
  fake_github.tree = [
    {"path": path, "type": "blob", "sha": f"base-{index}", "size": len(content)}
    for index, (path, content) in enumerate(DEFAULT_BRANCH.items())
  ]
  fake_github.blobs.update({f"base-{index}": content for index, content in enumerate(DEFAULT_BRANCH.values())})
  asyncio.run(index_repository(db_session, fake_github, FakeEmbedder(), 1))


def test_impact_lists_changed_symbols_and_the_code_that_uses_them(client, db_session, fake_github, changed_invoices):
  index_default_branch(db_session, fake_github)

  body = client.get(f"/pull-requests/{changed_invoices}/impact").json()

  assert body["indexed"] and not body["truncated"]
  symbols = {file["path"]: [(s["name"], s["kind"], s["change"]) for s in file["symbols"]] for file in body["changed"]}
  assert symbols == {
    "app/invoices.py": [("load_invoice", "function", "modified")],
    "app/payments.py": [("refund_payment", "function", "added")],
  }
  dependents = {d["path"]: (d["is_test"], d["uses"], d["changed_files"]) for d in body["dependents"]}
  assert dependents == {
    "app/routes.py": (False, ["load_invoice"], ["app/invoices.py"]),
    "tests/test_invoices.py": (True, ["load_invoice"], ["app/invoices.py"]),
  }
  routes = next(d for d in body["dependents"] if d["path"] == "app/routes.py")
  assert [(c["name"], c["start_line"], c["end_line"]) for c in routes["chunks"]] == [("show_invoice", 1, 3)]


def test_without_an_index_only_the_changes_are_known(client, changed_invoices):
  body = client.get(f"/pull-requests/{changed_invoices}/impact").json()

  assert not body["indexed"] and body["dependents"] == []
  symbols = {file["path"]: [(s["name"], s["change"]) for s in file["symbols"]] for file in body["changed"]}
  assert symbols == {"app/invoices.py": [("load_invoice", "changed")], "app/payments.py": [("refund_payment", "added")]}
  assert client.get("/pull-requests/99/impact").status_code == 404


def test_a_pr_merged_before_the_index_was_built_cannot_tell_added_from_modified(client, db_session, fake_github, changed_invoices):
  from datetime import datetime, timezone

  from app.db.models import PullRequest

  pull_request = db_session.get(PullRequest, changed_invoices)
  pull_request.merged_at = datetime(2024, 6, 2, tzinfo=timezone.utc)  # the index below is built later
  db_session.commit()
  index_default_branch(db_session, fake_github)

  body = client.get(f"/pull-requests/{changed_invoices}/impact").json()

  symbols = {file["path"]: [(s["name"], s["change"]) for s in file["symbols"]] for file in body["changed"]}
  assert symbols == {"app/invoices.py": [("load_invoice", "changed")], "app/payments.py": [("refund_payment", "added")]}
  assert [d["path"] for d in body["dependents"]] == ["app/routes.py", "tests/test_invoices.py"]  # users are still found
