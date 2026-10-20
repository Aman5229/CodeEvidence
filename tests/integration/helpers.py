"""Shared by the review feature tests: a PR synced through the webhook, and a fake model that
answers each kind of prompt (findings, summary, diagram, learning, chat) with a script."""

import json

from tests.integration.test_github_webhook import pr_payload, repo_payload, send_webhook

HANDLER_PATCH = """@@ -1,2 +1,3 @@
 def handler(request):
-    return load(request.args["id"])
+    item_id = request.args["id"]
+    return eval(item_id)"""
HANDLER_BLOB = b'def handler(request):\n    item_id = request.args["id"]\n    return eval(item_id)\n'
UTIL_PATCH = """@@ -0,0 +1,2 @@
+def slugify(text):
+    return text.lower().replace(" ", "-")"""
UTIL_BLOB = b'def slugify(text):\n    return text.lower().replace(" ", "-")\n'

FINDING = {
  "path": "app/handler.py", "line": 3, "severity": "high", "category": "security",
  "claim": "eval runs the id from the request as code: anyone can run Python on the server.",
  "quote": "return eval(item_id)", "evidence": ["H1", "S1"], "suggestion": "Use int(item_id).",
  "replacement": "    return int(item_id)", "confidence": 0.9,
}
UTIL_FINDING = {
  "path": "app/util.py", "line": 2, "severity": "medium", "category": "bug",
  "claim": "Only spaces are replaced, so tabs and other characters end up in the slug.",
  "quote": 'return text.lower().replace(" ", "-")', "evidence": ["H2"], "suggestion": None,
  "replacement": None, "confidence": 0.8,
}
DIAGRAM = "sequenceDiagram\n    participant Client\n    Client->>handler: request\n    handler-->>Client: eval(item_id)"


def file_entry(path: str, patch: str, sha: str, status: str = "modified") -> dict:
  added = sum(line.startswith("+") for line in patch.splitlines()[1:])
  removed = sum(line.startswith("-") for line in patch.splitlines()[1:])
  return {"filename": path, "status": status, "additions": added, "deletions": removed,
          "changes": added + removed, "patch": patch, "sha": sha}


def scripted(*, findings=(), summary="Handler now evaluates the request id in app/handler.py.", diagram="NONE",
             rule=None, path_glob=None, chat="It evaluates the request id [H1]."):
  """A fake model's answers, by prompt: every review call gets the same script."""

  def reply(system: str, user: str) -> str:
    if system.startswith("You keep a short list of rules"):
      return json.dumps({"rule": rule, "path_glob": path_glob})
    if system.startswith("You draw one Mermaid"):
      return diagram
    if system.startswith("You answer questions"):
      return chat
    if system.startswith("You summarise"):
      return summary
    return json.dumps({"findings": list(findings)})

  return reply


def sync_pull_request(client, fake_github, worker, files: list[dict], blobs: dict[str, bytes], *,
                      head_sha: str = "b" * 40, delivery: str = "d-open", action: str = "opened") -> int:
  """Send a pull_request webhook and run the jobs it queues; returns the PR's id."""
  fake_github.files = files
  fake_github.blobs.update(blobs)
  payload = {"action": action, "repository": repo_payload(), "pull_request": pr_payload(head_sha=head_sha)}
  send_webhook(client, delivery, "pull_request", payload)
  worker.run()
  assert worker.failures == []
  return client.get("/repositories/1/pull-requests").json()["items"][0]["id"]


def review(client, worker, pull_request_id: int, mode: str = "auto") -> dict:
  assert client.post(f"/pull-requests/{pull_request_id}/review", params={"mode": mode}).status_code == 202
  worker.run()
  assert worker.failures == []
  return client.get(f"/pull-requests/{pull_request_id}/review").json()


def comment_payload(body: str, *, comment_id: int = 501, association: str = "MEMBER", review_thread: int | None = None) -> tuple[str, dict]:
  """(event type, payload) of a new comment on PR #7: in the conversation, or in a review thread."""
  comment = {"id": comment_id, "body": body, "user": {"login": "maintainer"}, "author_association": association}
  if review_thread is None:
    return "issue_comment", {
      "action": "created", "repository": repo_payload(),
      "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/repos/octo/demo/pulls/7"}},
      "comment": comment,
    }
  return "pull_request_review_comment", {
    "action": "created", "repository": repo_payload(), "pull_request": pr_payload(),
    "comment": {**comment, "in_reply_to_id": review_thread},
  }
