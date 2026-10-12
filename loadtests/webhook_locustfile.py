"""Load on POST /webhooks/github: signed deliveries, each with a new delivery id.

Sends `push` events with the sample PR payload as the body. They take the same webhook path
as pull_request events (verify, store, queue, 202), but the worker does not call GitHub
for them, so a load test does not use up the GitHub API rate limit.
See doc/performance.md for how to run it.
"""
import hashlib
import hmac
import uuid
from pathlib import Path

from locust import HttpUser, between, task

from app.core.config import settings

BODY = Path("scripts/sample_payloads/test_pr_payload.json").read_bytes()
SIGNATURE = "sha256=" + hmac.new(
  settings.github_webhook_secret.encode(), BODY, hashlib.sha256
).hexdigest()


class GitHubSender(HttpUser):
  wait_time = between(0.1, 0.5)

  @task
  def deliver(self):
    self.client.post(
      "/webhooks/github",
      data=BODY,
      headers={
        "X-GitHub-Delivery": f"load-{uuid.uuid4()}",
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": SIGNATURE,
        "Content-Type": "application/json",
      },
      name="POST /webhooks/github",
    )
