"""GET /events/{delivery_id}, GET /jobs (dead letters) and POST /jobs/{id}/retry."""

from sqlalchemy import select

from app.db.models import JobRun
from tests.integration.test_github_webhook import pr_payload, repo_payload, send_webhook


def deliver_pr(client, delivery_id="d-1"):
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}
  assert send_webhook(client, delivery_id, "pull_request", payload).status_code == 202


def dead_letter(client, worker, fake_github):
  """A delivered PR whose file sync failed for good (a 404 is never retried)."""
  fake_github.should_fail = True
  fake_github.status_code = 404
  deliver_pr(client)
  worker.run()
  fake_github.should_fail = False


# ---------- GET /events/{delivery_id} ----------

def test_event_shows_its_jobs_while_queued(client):
  deliver_pr(client)

  body = client.get("/events/d-1").json()

  assert body["github_delivery_id"] == "d-1"
  assert body["status"] == "received"
  assert [(job["job_type"], job["status"]) for job in body["jobs"]] == [("process_event", "queued")]


def test_event_shows_every_job_after_processing(client, worker):
  deliver_pr(client)
  worker.run()

  body = client.get("/events/d-1").json()

  assert body["status"] == "processed"
  assert [(job["job_type"], job["status"], job["attempts"]) for job in body["jobs"]] == [
    ("process_event", "succeeded", 1),
    ("sync_pr_files", "succeeded", 1),
  ]


def test_unknown_event_is_404(client):
  assert client.get("/events/nope").status_code == 404


# ---------- GET /jobs ----------

def test_dead_letters_are_listed_by_default(client, worker, fake_github):
  dead_letter(client, worker, fake_github)

  items = client.get("/jobs").json()["items"]

  assert [(job["job_type"], job["status"]) for job in items] == [("sync_pr_files", "failed")]
  assert "404" in items[0]["last_error"]


def test_jobs_can_be_listed_by_status(client, worker):
  deliver_pr(client)
  worker.run()

  succeeded = client.get("/jobs", params={"status": "succeeded"}).json()["items"]

  assert [job["job_type"] for job in succeeded] == ["sync_pr_files", "process_event"]  # newest first
  assert client.get("/jobs").json()["items"] == []


def test_job_list_pages_with_a_cursor(client, worker):
  for number in range(3):
    deliver_pr(client, f"d-{number}")
  worker.run()

  first = client.get("/jobs", params={"status": "succeeded", "limit": 4}).json()
  second = client.get(
    "/jobs", params={"status": "succeeded", "limit": 4, "cursor": first["next_cursor"]}
  ).json()

  ids = [job["id"] for job in first["items"] + second["items"]]
  assert len(ids) == 6 and len(set(ids)) == 6
  assert second["next_cursor"] is None


def test_bad_status_is_422(client):
  assert client.get("/jobs", params={"status": "weird"}).status_code == 422


# ---------- POST /jobs/{job_id}/retry ----------

def test_dead_letter_can_be_retried_after_the_cause_is_fixed(client, db_session, worker,
                                                            fake_github, fake_broker):
  dead_letter(client, worker, fake_github)
  job_id = client.get("/jobs").json()["items"][0]["id"]

  response = client.post(f"/jobs/{job_id}/retry")
  assert response.status_code == 202
  assert response.json()["status"] == "queued"
  assert fake_broker.jobs == [("sync_pr_files", job_id)]

  worker.run()  # GitHub works again

  db_session.expire_all()
  job = db_session.get(JobRun, job_id)
  assert (job.status, job.attempts, job.last_error) == ("succeeded", 2, None)
  assert client.get("/jobs").json()["items"] == []


def test_only_failed_jobs_can_be_retried(client, worker):
  deliver_pr(client)
  worker.run()
  job_id = client.get("/jobs", params={"status": "succeeded"}).json()["items"][0]["id"]

  response = client.post(f"/jobs/{job_id}/retry")

  assert response.status_code == 409
  assert response.json()["error"]["code"] == "conflict"


def test_retry_of_unknown_job_is_404(client):
  assert client.post("/jobs/999/retry").status_code == 404


def test_retry_that_cannot_be_queued_stays_failed(client, db_session, worker, fake_github,
                                                  fake_broker):
  dead_letter(client, worker, fake_github)
  job_id = client.get("/jobs").json()["items"][0]["id"]
  fake_broker.should_fail = True

  response = client.post(f"/jobs/{job_id}/retry")

  assert response.status_code == 503
  db_session.expire_all()
  assert db_session.scalars(select(JobRun.status).where(JobRun.id == job_id)).one() == "failed"
