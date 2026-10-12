# Background jobs

How work moves from a GitHub webhook to the database, what is guaranteed on the way, and
what happens when something fails. The choice of Celery is explained in
[decisions.md](decisions.md); measurements are in [performance.md](performance.md).

## The path of one webhook

```
POST /webhooks/github
  verify signature -> store event -> create job_runs row (queued) -> COMMIT -> send {"job_id"} to Redis -> 202
                                                                                  |
worker:  process_event   upsert repository and PR (database only) -> clear cache -> queue sync_pr_files
         sync_pr_files   fetch the PR's files from GitHub -> replace stored files -> clear cache
```

- **Only the job's id travels through Redis.** What to do (the payload, ids only) is stored in
  the `job_runs` row, and the event's raw GitHub payload is stored in `github_events`.
- **Rows are committed before the message is sent.** The worker uses its own database
  connection, so it only sees committed rows.
- **Two jobs instead of one.** `process_event` touches only our database and is fast.
  `sync_pr_files` calls GitHub and is the step that fails. Retrying it does not repeat
  the event processing.

## Job states (`job_runs.status`)

| Status | Meaning |
|---|---|
| `queued` | Row created and message sent to Redis; no worker has started it yet |
| `running` | A worker is running it (`attempts` was increased) |
| `retrying` | It failed with a transient error and is scheduled to run again |
| `succeeded` | Done (`finished_at` set) |
| `failed` | Failed for good (`finished_at` set): a **dead letter**. It will not run again unless a person retries it |

Follow a delivery with `GET /events/{delivery_id}`, which shows the event and every job it
started. List dead letters with `GET /jobs` (defaults to `status=failed`), and queue one again
with `POST /jobs/{job_id}/retry` once the cause is fixed.

## Delivery semantics

- **At-least-once.** Jobs are acknowledged after they finish (`task_acks_late`), and a worker
  process that dies puts its job back on the queue (`task_reject_on_worker_lost`). A job is
  not lost when a worker crashes, but it can run twice.
- **Effectively once.** Every step is safe to repeat, so running a job twice leaves the same
  result as running it once: upserts, "replace the PR's files", a PR payload older than
  the stored row is ignored, and the first `processed_at` is kept. See the idempotency entry
  in [decisions.md](decisions.md).
- **Exactly-once is not claimed.** It cannot be guaranteed across a network; idempotent
  steps give the same effect.

## Retry policy

| Error | Retried? |
|---|---|
| Timeouts and connection errors (`httpx.TransportError`) | yes |
| HTTP 429, 500, 502, 503, 504 | yes |
| HTTP 401, 403, 404, 422 | no: it would fail the same way every time |
| Errors in our own code or data (`KeyError`, `ValueError`, ...) | no: needs a fix, not a retry |

- Up to **5 retries** (6 attempts in total), then the job is `failed`.
- Wait before retry *n* (starting at 0): a random time between 0 and
  `min(300 s, 5 s × 2^n)` ("full jitter"). Ceilings: 5, 10, 20, 40, 80 s.
  The randomness spreads out jobs that failed at the same moment, so they do not all
  hit GitHub again at the same instant.
- GitHub's rate-limit 403 responses are not retried yet; they need the reset time from the
  `X-RateLimit-*` headers, which is planned for the resilience milestone.

## Failure modes

| What fails | What happens | How it recovers |
|---|---|---|
| Bad signature, bad JSON, missing header | 401 / 400, nothing stored | GitHub shows the delivery as failed |
| Redis unreachable when queueing | Event and job marked `failed`, webhook returns 503 | GitHub's "Redeliver" queues it again |
| Same delivery sent twice at once | Unique constraint; the second request gets 200 `duplicate_ignored` | nothing to do |
| GitHub slow, overloaded or down | `sync_pr_files` retried with backoff; the PR row is already saved | automatic; after 6 attempts a dead letter, `POST /jobs/{id}/retry` |
| GitHub returns 404 / 401 | `sync_pr_files` failed at once (dead letter) | fix the cause, then `POST /jobs/{id}/retry` |
| Worker killed mid-job | The job goes back on the queue and runs again (idempotent) | automatic |
| Worker stopped (`docker compose stop`) | Warm shutdown: no new jobs, running jobs finish (up to 60 s, `stop_grace_period`) | automatic |
| Two events for the same PR finish out of order | The older payload is ignored (`updated_at` check) | automatic |
| App crashes after commit but before the message is sent | Event `received` with a `queued` job that never runs | **not handled.** `GET /jobs?status=queued` finds such jobs, but the retry endpoint only accepts `failed` jobs, and GitHub's Redeliver is treated as a duplicate. The transactional outbox (a stretch task, not built) is the fix |

## Running and watching the worker

```bash
docker compose logs -f worker                               # job received / succeeded / retry lines
WORKER_CONCURRENCY=4 docker compose up -d worker            # more worker processes
docker compose exec worker celery -A app.worker call app.jobs.ping   # is it alive?
```
