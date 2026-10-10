"""Simulated dashboard traffic against the synthetic repositories.

Mix: 40% PR lists (a few common filters), 20% repository stats, 40% PR details
(from each repository's 100 most recent PRs). See doc/performance.md for how to run it.
"""
import random

from locust import HttpUser, between, task

LIST_FILTERS = [{}, {"status": "open"}, {"merged": "true"}, {"is_bot": "false"}]


class DashboardUser(HttpUser):
  wait_time = between(0.1, 0.5)  # think time between requests, per simulated user

  def on_start(self):
    """Find the synthetic repositories and their recent PR ids (reported as "setup")."""
    repositories = self.client.get("/repositories?limit=100", name="setup").json()["items"]
    self.repository_ids = [
      repo["id"] for repo in repositories if repo["full_name"].startswith("synthetic/")
    ]
    if not self.repository_ids:
      raise RuntimeError("No synthetic repositories: run python -m scripts.seed_synthetic_data")

    self.pull_request_ids = []
    for repository_id in self.repository_ids:
      page = self.client.get(
        f"/repositories/{repository_id}/pull-requests?limit=100", name="setup"
      ).json()
      self.pull_request_ids += [item["id"] for item in page["items"]]

  @task(4)
  def list_pull_requests(self):
    self.client.get(
      f"/repositories/{random.choice(self.repository_ids)}/pull-requests",
      params=random.choice(LIST_FILTERS),
      name="/repositories/[id]/pull-requests",
    )

  @task(2)
  def repository_stats(self):
    self.client.get(
      f"/repositories/{random.choice(self.repository_ids)}/stats",
      name="/repositories/[id]/stats",
    )

  @task(4)
  def pull_request_detail(self):
    self.client.get(
      f"/pull-requests/{random.choice(self.pull_request_ids)}",
      name="/pull-requests/[id]",
    )
