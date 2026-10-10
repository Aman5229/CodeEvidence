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
