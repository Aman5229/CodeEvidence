# Decision log

Each entry: the options considered, the choice, why, and what it costs.
The measurements behind performance decisions are in [performance.md](performance.md).

## Indexes for the read API (10 Oct 2026)

**Context.** At 100,000 PRs, `EXPLAIN ANALYZE` showed every PR list page reading all
10,000 PRs of a repository and sorting them to return 21. The only indexes were the ones
created by primary keys and unique constraints.

**Options considered**

| Index | Decision | Evidence |
|---|---|---|
| `pull_requests (repository_id, created_at, id)` | **Added** | First page 8.3 to 0.23 ms; cursor page 6.3 to 0.18 ms. Matches the filter, the sort and the keyset cursor in one index. |
| `pull_requests (repository_id, author_login, created_at, id)` | Not added | `author=` filter stays at about 5 ms. Acceptable at this size; not worth a second index on every write. |
| `pull_requests (merged_at)` | Not added | About 31% of PRs are merged: not selective enough to beat a scan. |
| `pull_request_files (pull_request_id)` | Not added | The unique index `(pull_request_id, path)` already serves this lookup (0.05 ms). |

**Column order.** `repository_id` comes first because every list query filters on it
by equality. `created_at, id` follow in the same order as `ORDER BY`, so rows come out
of the index already sorted, and the cursor `(created_at, id) < (...)` becomes a range scan.
The index is ascending; Postgres reads it backward for the newest-first order.

**Trade-offs**
- Every insert and update of a PR now also updates this index. Webhooks and backfills
  write far less often than the API reads, so the trade is worth it.
- The index did not improve end-to-end latency under load, because the app process's CPU
  was the bottleneck, not the query. The index still matters: it keeps the list query
  cheap as repositories grow, instead of growing with the repository's size.
- Repository stats remains a sequential scan over all file rows. An index cannot fix it;
  storing each PR's line totals on the PR row at ingest could. That was deferred, and the
  Redis cache covers it for now.

## Job queue: Celery with Redis (10 Oct 2026)

**Context.** The webhook does all its work inside the HTTP request: store the event, call
the GitHub API for the PR's files, write everything, then answer. GitHub waits only 10 s
for a response, a GitHub outage becomes our outage, and later work (repository indexing,
embeddings, LLM review) takes minutes. The work has to move to a background worker.

**Options considered** (checked on PyPI in October 2026)

| | Celery | RQ | Dramatiq | ARQ |
|---|---|---|---|---|
| Latest release | 5.6.3 (Mar 2026) | 2.12.0 (Aug 2026) | 2.2.1 (Sep 2026) | 0.28.0 (Apr 2026), maintenance-only mode |
| Job style | sync | sync | sync | async |
| Brokers | Redis, RabbitMQ, others | Redis | Redis, RabbitMQ | Redis |
| Complexity | high | low | medium | low |
| Seen in job posts | very often | sometimes | rarely | rarely |

**Choice: Celery, with Redis as the broker.**

**Why**
- It is the most widely used Python job queue and is actively maintained. ARQ, the earlier
  favourite because it is async, is in maintenance-only mode.
- At-least-once delivery is available: with `task_acks_late`, a job is acknowledged only
  after it finishes, so a worker crash makes it run again instead of losing it.
- Redis is already in the stack, so no new service is needed.

**Trade-offs**
- More configuration than RQ, and settings with sharp edges (late acks, Redis visibility
  timeout, prefork worker processes).
- Celery jobs are sync, while the ingestion code is async. Each job calls it with
  `asyncio.run(...)`, which costs little per job.
- `kombu`, Celery's messaging library, requires `redis < 6.5`, so the Redis client moves
  from 8.x to 6.x. The app only uses basic commands, which 6.x supports.
- At-least-once means a job can run twice. Jobs must be idempotent, which is planned.

## Idempotent jobs: repeatable steps, not skip-on-redelivery (12 Oct 2026)

**Context.** Jobs are acknowledged after they finish (at-least-once delivery). A worker that
crashes after doing the work but before acknowledging gets the same job again. Two worker
processes can also finish events for the same PR in any order.

**Options considered**
- **Skip a job whose event is already processed.** Simple, but it can lose follow-up work:
  if the worker crashed after the commit but before queueing `sync_pr_files`, the re-run
  would skip and the files would never sync.
- **Make every step safe to repeat.** Upserts instead of inserts, "replace the PR's files"
  instead of "add files", and never let older data overwrite newer data.

**Choice: make every step safe to repeat.**

| Step | Why running it twice is safe |
|---|---|
| Webhook, same delivery id | Duplicate check, backed by a unique constraint. A simultaneous duplicate hits the constraint and is answered as a duplicate (200). |
| `upsert_repository` | Returns the existing row. |
| `upsert_pull_request` | Ignores a payload whose `updated_at` is older than the stored row. |
| `mark_event_completed` | Keeps the first `processed_at`. |
| `sync_pr_files` | Replaces the PR's files with GitHub's current list. |

**Trade-offs**
- A repeated job repeats its work, for example one extra GitHub call for the file sync.
- Ordering relies on GitHub's `updated_at`, which has one-second precision. Two changes in the
  same second are treated as the same version, and the later one to be processed wins.
- Two file syncs for the same PR running at the same moment can conflict on the
  `(pull_request_id, path)` unique constraint. One fails and needs a retry (planned next).

## Job tracking and dead letters in one table (12 Oct 2026)

**Context.** Jobs need retries with backoff, a place for jobs that keep failing (dead letters),
and a visible status per webhook delivery.

**Options considered**
- Celery's own state (result backend in Redis) plus a separate dead-letter table.
- **One `job_runs` table in Postgres**: one row per job with its type, payload, status,
  attempts and last error. Failed rows are the dead letters.

**Choice: one `job_runs` table.** Postgres is the system of record; job state can be queried
and joined with events; and only `{"job_id": N}` needs to travel through Redis. Retries use
Celery's `retry` with our own countdown (exponential backoff with full jitter, 5 retries),
and only for transient errors (timeouts, 429, 5xx).

**Trade-offs**
- Two extra writes per job (running, then finished).
- If the app crashes after committing a job but before sending its message, the job stays
  `queued`. The transactional outbox would close that gap; it was skipped as a stretch task.

## Webhook route must not be `async def` (12 Oct 2026)

**Context.** The first webhook load test gave 4.9 requests/s, a p95 of 21 s and failures:
the database pool ran out because blocking calls inside an `async def` route froze the
event loop while other requests held connections.

**Choice.** Routes that make blocking calls are plain `def`; FastAPI runs them in its thread
pool. Only work that is truly async (reading the request body) stays `async`. Result:
47 requests/s, p95 1.5 s, no failures. The rule for this codebase: no blocking call inside
`async def`. Moving to async database drivers would be the alternative, but it changes every
query and is not needed at this load.
