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

Retries happen in one place only: the job (`run_tracked` in `app/jobs.py`). The GitHub client
makes one attempt per call, so a failure is never retried at two levels (6 job attempts x 3
client attempts would be 18 calls for one failure).

| Error | What the job does |
|---|---|
| Timeouts and connection errors (`httpx.TransportError`) | retry with backoff; uses the failure budget |
| HTTP 500, 502, 503, 504, and 429 without rate-limit headers | retry with backoff; uses the failure budget |
| Rate limit: 403/429 with `Retry-After`, or `X-RateLimit-Remaining: 0` | **pause** until the reset time; does not use the budget |
| GitHub paused for every worker (rate limit or open circuit) | **pause** for the remaining time; does not use the budget |
| HTTP 401, 403 (without rate-limit headers), 404, 422 | no retry: fails at once |
| Errors in our own code or data (`KeyError`, `ValueError`, ...) | no retry: needs a fix |

- **Failure budget:** 5 retries after real failures (6 attempts), then the job is `failed`.
  The count travels with the job's message (`{"job_id", "failures"}`); waiting out a pause
  does not use it.
- **Backoff:** before retry *n* (from 0), a random wait between 0 and `min(300 s, 5 s × 2^n)`
  ("full jitter"); ceilings 5, 10, 20, 40, 80 s.
- **Pauses** wait the time GitHub asked for, plus up to 1 s of jitter, capped at 900 s. The cap
  keeps every wait well below Redis's visibility timeout (1 hour): a message held longer than
  that would be delivered a second time.
- **Celery's own retry limit is off** (`max_retries=None` on the tasks). Celery counts every
  retry, pauses included, and would drop a job that paused a few times; the fault-injection
  test found this (see decisions.md).

## Protecting GitHub: rate-limit pause and circuit breaker

`app/integrations/github/guard.py`, with its state in Redis so every worker process shares it.

- **Rate-limit pause.** When one job gets a rate-limit response, it sets
  `github:rate_limited` with a TTL until GitHub's reset time. Every job checks this key before
  calling GitHub and pauses instead, so no worker keeps hitting a rate-limited API.
- **Circuit breaker.** States: **closed** (normal) → **open** after 5 transient failures in a
  row within 60 s (a success resets the count) → after 30 s **half-open**: exactly one job is
  let through to test GitHub, the others keep waiting → **closed** if it succeeds, **open**
  again if it fails. While open, jobs pause without calling GitHub, so a GitHub outage costs
  no calls and no failure budget. Scattered failures (for example 30% at random) rarely come
  5 in a row; they are handled by retries, and the breaker stays closed.

## Failure modes

| What fails | What happens | How it recovers |
|---|---|---|
| Bad signature, bad JSON, missing header | 401 / 400, nothing stored | GitHub shows the delivery as failed |
| Redis unreachable when queueing | Event and job marked `failed`, webhook returns 503 | GitHub's "Redeliver" queues it again |
| Same delivery sent twice at once | Unique constraint; the second request gets 200 `duplicate_ignored` | nothing to do |
| GitHub slow or failing now and then | `sync_pr_files` retried with backoff; the PR row is already saved | automatic; after 6 failed attempts a dead letter, `POST /jobs/{id}/retry` |
| GitHub down (an outage) | Circuit opens after 5 failures in a row; jobs pause instead of calling; one test call every 30 s | automatic when GitHub recovers |
| GitHub rate limit reached | Every worker pauses until GitHub's reset time | automatic |
| Retry cannot be scheduled (Redis down) | Job marked `failed` (dead letter), never left `retrying` | `POST /jobs/{id}/retry` |
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

## Fault injection (proof)

`tests/integration/test_queue_end_to_end.py` runs a real Celery worker against Redis with a
fake GitHub:

| Scenario | Result (12 Oct 2026) |
|---|---|
| 40 PR events, 30% of GitHub calls fail at random | all 80 jobs succeeded, every PR got its files; 62 GitHub calls, 22 failed and were retried |
| 20 PR events, GitHub down for its first 12 calls, then healthy | all 40 jobs succeeded; the open circuit paused runs instead of calling GitHub |

Both ran 6 times in a row without a failure after the Celery retry-limit fix (before it, the
outage scenario lost a job in 5 of 6 runs).

