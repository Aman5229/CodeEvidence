"""Repository settings, one-click fixes, the walkthrough and merge check, and incremental reviews,
end to end with a fake GitHub and a fake model."""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models import ReviewFinding
from tests.integration.helpers import (
  DIAGRAM,
  FINDING,
  HANDLER_BLOB,
  HANDLER_PATCH,
  UTIL_BLOB,
  UTIL_FINDING,
  UTIL_PATCH,
  file_entry,
  review,
  scripted,
  sync_pull_request,
)

UTIL_PATCH_2 = """@@ -0,0 +1,3 @@
+def slugify(text):
+    cleaned = text.strip()
+    return cleaned.lower().replace(" ", "-")"""
UTIL_BLOB_2 = b'def slugify(text):\n    cleaned = text.strip()\n    return cleaned.lower().replace(" ", "-")\n'
NEW_UTIL_FINDING = {
  **UTIL_FINDING, "line": 3, "quote": 'return cleaned.lower().replace(" ", "-")', "evidence": ["H1"],
}


@pytest.fixture
def pull_request_id(client, fake_github, worker):
  return sync_pull_request(client, fake_github, worker, [file_entry("app/handler.py", HANDLER_PATCH, "h1")], {"h1": HANDLER_BLOB})


@pytest.fixture
def publishing(monkeypatch):
  monkeypatch.setattr(settings, "publish_repositories", "octo/demo")


# ---------- repository settings ----------

def test_settings_and_guidelines_from_the_default_branch_shape_the_review(client, fake_github, fake_llm, worker):
  fake_github.repo_files = {
    ".codeevidence.yaml": b'profile: assertive\nexclude:\n  - "docs/**"\ninstructions:\n'
                          b'  - path: "app/**"\n    text: "Never evaluate request data."\n',
    "CLAUDE.md": b"Every handler must validate its input.\n",
  }
  pull_request_id = sync_pull_request(
    client, fake_github, worker,
    [file_entry("app/handler.py", HANDLER_PATCH, "h1"), file_entry("docs/notes.md", "@@ -0,0 +1 @@\n+Notes", "n1", "added")],
    {"h1": HANDLER_BLOB},
  )
  fake_llm.answers = scripted(findings=[FINDING])

  body = review(client, worker, pull_request_id)

  evidence = {item["id"]: (item["kind"], item["path"]) for item in body["evidence"]}
  assert evidence["P1"] == ("instruction", "app/**")
  assert evidence["G1"] == ("guideline", "CLAUDE.md")
  assert "docs/notes.md" not in {path for _, path in evidence.values()}  # excluded by the settings
  config = body["config"]
  assert (config["source"], config["profile"], config["error"]) == ("file", "assertive", None)
  assert config["guideline_files"] == ["CLAUDE.md"]
  _, user = fake_llm.calls[0]
  assert "Never evaluate request data." in user and "Every handler must validate its input." in user


def test_a_broken_settings_file_never_blocks_a_review(client, fake_github, fake_llm, worker, pull_request_id):
  fake_github.repo_files = {".codeevidence.yaml": b"profile: loud\n"}
  fake_llm.answers = scripted(findings=[FINDING])

  body = review(client, worker, pull_request_id)

  assert body["status"] == "completed" and len(body["findings"]) == 1
  assert body["config"]["profile"] == "chill"  # the defaults
  assert "profile: Input should be 'chill' or 'assertive'" in body["config"]["error"]


def test_the_settings_endpoint_reads_the_default_branch(client, fake_github, pull_request_id):
  assert client.get("/repositories/1/config").json()["source"] == "default"

  fake_github.repo_files = {".codeevidence.yaml": b"tools:\n  gitleaks: false\n", "AGENTS.md": b"Use type hints."}
  config = client.get("/repositories/1/config").json()

  assert (config["source"], config["tools"]["gitleaks"], config["guideline_files"]) == ("file", False, ["AGENTS.md"])
  assert client.get("/repositories/99/config").status_code == 404


# ---------- one-click fixes, diagram, effort ----------

def test_a_finding_comes_with_a_checked_one_click_fix(client, fake_llm, worker, pull_request_id):
  fake_llm.answers = scripted(findings=[FINDING], diagram=DIAGRAM)

  body = review(client, worker, pull_request_id)

  (finding,) = body["findings"]
  assert finding["replacement"] == "    return int(item_id)"
  assert finding["original_line"] == "    return eval(item_id)"
  assert finding["agent_prompt"].startswith("In `app/handler.py` at line 3: eval runs the id")
  assert body["diagram"].startswith("sequenceDiagram") and "handler" in body["diagram"]
  assert body["effort"] == {"level": 1, "minutes": 5}
  assert body["pull_request_url"] == "https://github.com/octo/demo/pull/7"


def test_a_fix_that_would_break_the_code_is_withheld(client, db_session, fake_llm, worker, pull_request_id):
  fake_llm.answers = scripted(findings=[{**FINDING, "replacement": "    return int(item_id"}])

  (finding,) = review(client, worker, pull_request_id)["findings"]

  assert finding["replacement"] is None
  assert db_session.scalars(select(ReviewFinding.replacement_rejected)).one() == "syntax_error"


# ---------- publishing ----------

def test_publishing_posts_the_fix_a_walkthrough_and_a_failing_check(client, fake_github, fake_llm, worker, pull_request_id, publishing):
  fake_llm.answers = scripted(findings=[FINDING], diagram=DIAGRAM)

  review(client, worker, pull_request_id)

  (posted,) = fake_github.reviews_posted
  assert "```suggestion\n    return int(item_id)\n```" in posted["comments"][0]["body"]
  assert "Prompt for AI agents" in posted["comments"][0]["body"]
  (walkthrough,) = fake_github.issue_comments
  assert walkthrough["body"].startswith("## CodeEvidence walkthrough")
  assert "```mermaid\nsequenceDiagram" in walkthrough["body"]
  (status,) = fake_github.statuses
  assert (status["state"], status["context"], status["sha"]) == ("failure", "codeevidence/review", "b" * 40)
  assert status["target_url"] == f"http://localhost:5173/pull-requests/{pull_request_id}"
  assert client.get(f"/pull-requests/{pull_request_id}/reviews").json()[0]["check_state"] == "failure"


def test_the_walkthrough_is_edited_in_place_and_comments_are_not_repeated(client, fake_github, fake_llm, worker, pull_request_id, publishing):
  fake_llm.answers = scripted(findings=[FINDING])
  review(client, worker, pull_request_id)
  fake_github.repo_files = {".codeevidence.yaml": b"profile: assertive\n"}  # a new input: not a cache hit
  fake_llm.answers = scripted(findings=[FINDING], summary="Handler in app/handler.py runs eval on input now.")

  review(client, worker, pull_request_id, mode="full")

  (walkthrough,) = fake_github.issue_comments
  assert "Handler in app/handler.py runs eval on input now." in walkthrough["body"]
  assert len(fake_github.reviews_posted) == 1  # the same finding is not posted twice
  assert len(fake_github.statuses) == 2


def test_the_merge_check_follows_the_settings(client, fake_github, fake_llm, worker, pull_request_id, publishing):
  fake_github.repo_files = {".codeevidence.yaml": b"merge_check:\n  block_on: never\n"}
  fake_llm.answers = scripted(findings=[FINDING])

  review(client, worker, pull_request_id)

  assert [(s["state"], s["description"]) for s in fake_github.statuses] == [("success", "No blocking findings; 1 to consider")]


def test_without_permission_for_statuses_the_rest_is_still_published(client, fake_github, fake_llm, worker, pull_request_id, publishing):
  fake_github.status_code_for_statuses = 403
  fake_llm.answers = scripted(findings=[FINDING])

  body = review(client, worker, pull_request_id)

  assert body["published_at"] is not None and body["check_state"] is None
  assert len(fake_github.reviews_posted) == 1 and len(fake_github.issue_comments) == 1


# ---------- incremental reviews ----------

@pytest.fixture
def two_files(client, fake_github, worker):
  return sync_pull_request(
    client, fake_github, worker,
    [file_entry("app/handler.py", HANDLER_PATCH, "h1"), file_entry("app/util.py", UTIL_PATCH, "u1", "added")],
    {"h1": HANDLER_BLOB, "u1": UTIL_BLOB},
  )


def push(client, fake_github, worker, *, util_patch=UTIL_PATCH_2, changed=("app/util.py",), status="ahead"):
  """A new commit on the PR's branch (head c...c): util.py changes, handler.py does not."""
  fake_github.comparison = {"status": status, "files": [{"filename": path} for path in changed]}
  sync_pull_request(
    client, fake_github, worker,
    [file_entry("app/handler.py", HANDLER_PATCH, "h1"), file_entry("app/util.py", util_patch, "u2", "added")],
    {"u2": UTIL_BLOB_2}, head_sha="c" * 40, delivery="d-push", action="synchronize",
  )


def test_new_commits_review_only_the_changed_files_and_keep_the_other_findings(client, fake_github, fake_llm, worker, two_files):
  fake_llm.answers = scripted(findings=[FINDING])
  first = review(client, worker, two_files)
  push(client, fake_github, worker)
  fake_llm.answers = scripted(findings=[NEW_UTIL_FINDING])
  calls_before = len(fake_llm.calls)

  second = review(client, worker, two_files)

  assert fake_github.compared == [("b" * 40, "c" * 40)]
  assert (second["mode"], second["base_review_id"], second["compared_from_sha"]) == ("incremental", first["id"], "b" * 40)
  _, user = fake_llm.calls[calls_before]
  assert "app/util.py" in user and "app/handler.py" not in user  # only the changed file was sent
  carried, new = second["findings"]  # the carried high finding still ranks first
  assert (carried["path"], carried["carried_from_review_id"]) == ("app/handler.py", first["id"])
  assert [(item["id"], item["kind"]) for item in carried["evidence"]] == [("C1", "hunk"), ("C2", "signal")]
  assert (new["path"], new["carried_from_review_id"]) == ("app/util.py", None)
  runs = client.get(f"/pull-requests/{two_files}/reviews").json()
  assert [(run["mode"], run["base_review_id"]) for run in runs] == [("incremental", first["id"]), ("full", None)]


def test_the_same_commit_reviewed_again_is_a_cache_hit(client, fake_github, fake_llm, worker, two_files):
  fake_llm.answers = scripted(findings=[FINDING])
  first = review(client, worker, two_files)
  push(client, fake_github, worker)
  fake_llm.answers = scripted(findings=[NEW_UTIL_FINDING])
  second = review(client, worker, two_files)

  again = review(client, worker, two_files)

  assert again["cached"] and again["llm_calls"] == 0
  assert (again["mode"], again["base_review_id"]) == ("incremental", first["id"])
  assert [f["quote"] for f in again["findings"]] == [f["quote"] for f in second["findings"]]


def test_when_only_unreviewed_files_changed_the_earlier_review_still_holds(client, fake_github, fake_llm, worker, two_files):
  fake_llm.answers = scripted(findings=[FINDING])
  first = review(client, worker, two_files)
  push(client, fake_github, worker, util_patch=UTIL_PATCH, changed=["docs/readme.md"])
  calls_before = len(fake_llm.calls)

  second = review(client, worker, two_files)

  assert len(fake_llm.calls) == calls_before and second["llm_calls"] == 0
  assert (second["mode"], second["summary"]) == ("incremental", first["summary"])
  assert [f["carried_from_review_id"] for f in second["findings"]] == [first["id"]]


@pytest.mark.parametrize("status", ["diverged", "behind"])
def test_a_rebase_or_force_push_means_a_full_review(client, fake_github, fake_llm, worker, two_files, status):
  fake_llm.answers = scripted(findings=[FINDING])
  review(client, worker, two_files)
  push(client, fake_github, worker, status=status)

  body = review(client, worker, two_files)

  assert (body["mode"], body["base_review_id"]) == ("full", None)


def test_a_vanished_base_commit_or_mode_full_means_a_full_review(client, fake_github, fake_llm, worker, two_files):
  fake_llm.answers = scripted(findings=[FINDING])
  review(client, worker, two_files)
  push(client, fake_github, worker)
  fake_github.comparison = None  # GitHub answers 404: the commit is gone

  assert review(client, worker, two_files)["mode"] == "full"
  compared = len(fake_github.compared)
  assert review(client, worker, two_files, mode="full")["mode"] == "full"
  assert len(fake_github.compared) == compared  # full never asks for a comparison


def test_feedback_follows_the_problem_into_later_reviews(client, fake_github, fake_llm, worker, two_files):
  fake_llm.answers = scripted(findings=[FINDING])
  first = review(client, worker, two_files)
  client.post(f"/findings/{first['findings'][0]['id']}/feedback", json={"verdict": "useful"})
  push(client, fake_github, worker)

  second = review(client, worker, two_files)

  carried = next(f for f in second["findings"] if f["path"] == "app/handler.py")
  assert carried["feedback"] == {"useful": 1, "not_useful": 0, "replies": 0}
