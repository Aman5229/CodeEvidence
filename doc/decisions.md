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

## Resilience: one retry layer, shared pause, circuit breaker (12 Oct 2026)

**Retries in one layer only.** The job retries; the GitHub client makes one attempt per call.
Retrying in both would multiply attempts (6 x 3 = 18 calls for one failure) and hide failures
from the job's status. The client gets explicit timeouts (connect 5 s, read 15 s) and follows
redirects (a renamed repository answers 301).

**Rate limits pause instead of retrying.** A rate-limited response gives the time to wait
(`Retry-After` or `X-RateLimit-Reset`). The first job that sees it stores a pause in Redis with
that TTL, and every worker waits it out. Pauses do not use a job's failure budget, which
travels with the message (`failures`).

**Circuit breaker in Redis.** Opens after 5 transient failures in a row within 60 s, stays
open 30 s, then lets exactly one call through (half-open) using `SET NX` on a probe key.
State is in Redis so all worker processes share it. Options considered: a breaker per
process (simple, but each process would learn about an outage separately and keep calling),
or a library (pybreaker; its Redis storage still needs the same design decisions).

**Bug found by fault injection.** Passing `max_retries=None` to Celery's `retry()` means "use
the task's default" (it was 5), not "unlimited". Celery's counter includes pauses, so a job
that waited out the open circuit several times was dropped while its row said `retrying`.
Fix: the tasks are declared with `max_retries=None`, and if a retry cannot be scheduled the job
becomes a dead letter instead of staying `retrying`.

**Trade-offs.** A half-open probe that hangs holds the probe key until it expires (30 s). The
breaker counts failures from any PR, so one broken repository could open it for all; scoping
it per repository was not needed yet.

## Observability and security for the read API (12 Oct 2026)

**JSON logs with context variables.** One JSON object per line, from our code and from
libraries. The request, delivery and job ids live in `contextvars` and are added to every
log record by a record factory, so code never has to pass them around. The job message
carries the ids, so the worker's lines match the webhook request that caused them.
Alternative: a logging library (structlog); stdlib logging was enough and adds no dependency.

**Metrics from the source of truth.** Request latency is a histogram in the app process. Job
counts, queue depth, cache counters and the breaker state are read at scrape time from
Postgres and Redis, because the worker runs in other processes. Alternative: Prometheus
multiprocess mode with metric files shared between processes; more moving parts and still
blind across containers.

**Liveness is not readiness.** `/health` checks only that the process runs; `/health/ready`
checks the database, cache and queue. Making liveness depend on the database would make an
orchestrator restart healthy app processes during a database outage, which fixes nothing.

**API keys stored as SHA-256 hashes.** Keys are 32 random bytes, so an unsalted fast hash is
safe; slow password hashes (bcrypt, argon2) protect guessable secrets and would add latency
to every request. Lookup is by hash, so the stored value is never compared with
attacker-chosen input byte by byte. Each request costs one indexed lookup (pinned by a test).

**Token bucket in Redis, failing open.** Allows bursts up to the capacity and a steady rate
after that. One Lua script makes the check atomic across app processes and uses Redis's
clock. If Redis is down the request is allowed: a missing rate limit for a while is better
than a read API that is down. Alternatives: fixed windows (bursts at window edges), sliding
logs (memory per request).

**Bug found while checking in Docker.** The key script read the new row's attributes after its
session had closed (`commit()` expires loaded objects), so it crashed before printing the
key. It now prints inside the session.

## Python 3.12 in Docker and CI (19 Oct 2026)

scikit-learn and NumPy releases now need Python 3.11 or newer, so the image and CI moved
from 3.10 to 3.12, the version used locally. `requires-python` is `>=3.11,<3.13`.

## ML risk model: proxy label, time split, shadow mode (19 Oct 2026)

**Label: closed without merge.** Available for every PR with no manual work; a proxy for
risk, not risk itself. Better labels (reverts, follow-up fixes) need data work and come later.

**Time-based split and time-ordered cross-validation.** A random split would train on the
future and look better than it is. Calibration and the threshold use the newest part of the
training set, never the test set.

**Features rebuilt for training, not read from the risk table.** Rescoring compares a PR with
all of its repository's PRs, including later ones: a leak. The dataset builder recomputes
size and author history from earlier PRs only, with the same feature function the server uses.

**Served in shadow mode with a rule fallback.** The model's probability is stored and shown
next to the rule score, which stays the primary answer. No model file means rules only.
**The model file is a pickle** (joblib): only files this project trained are ever loaded.

## Retrieval: pgvector, HNSW, hybrid with RRF, a local model (19 Oct 2026)

**pgvector instead of a vector database.** The chunks live next to the data they belong to,
in the database we already run and back up; joins and filters by repository are plain SQL.
A separate vector store (Qdrant, Pinecone) is worth it at far larger scale.

**HNSW index, cosine distance.** No training step and good recall as rows are added;
IVFFlat needs data to train on and degrades without rebuilds.

**Hybrid retrieval merged with reciprocal rank fusion.** Vector search finds similar meaning,
keyword search finds the same names; RRF merges ranks, so no score scaling to tune.

**Local open-source embeddings** (`BAAI/bge-small-en-v1.5`, 384 dimensions): free, private,
CPU-only. Behind an interface with a deterministic fake, used in every test.

**Chunks follow the syntax tree** (tree-sitter), so a hit is a whole function with its
name and line range; windows only as a fallback.

## AI review: Claude, verification before ranking, cost guards (19 Oct 2026)

**Anthropic Claude behind a provider interface,** with a fake provider in all tests and CI.

**Findings must quote the code they are about.** That makes every claim checkable with plain
string matching; findings that do not check out are dropped (and stored, to measure the
hallucination rate). No second LLM call for verification: deterministic checks first.

**Prompt injection:** PR content only in the user message, inside a tag named after a hash
of that content, with a system rule never to follow instructions in it; the model has no
tools; verification drops anything not about added lines.

**Per-review budget checked before each call** (worst case: prompt + full output), a clean
`budget_exceeded` stop, the M5 retry/pause/breaker patterns reused (`LLMGuard`), and a
content-addressed cache (hash of the exact model input) so a re-run costs nothing.

## Publishing reviews: a token now, a GitHub App later (19 Oct 2026)

**A fine-grained token limited to one sandbox repository,** plus an allowlist in the app
(`PUBLISH_REPOSITORIES`). A GitHub App (its own bot identity, per-installation tokens and
permissions) is the right design for other people's repositories; not needed for a sandbox.

**Idempotency by a hidden marker in each comment** (a hash of path, category and quoted
code), checked against the PR's existing comments before posting. GitHub has no
idempotency keys, so the state on GitHub itself is the source of truth.

**Evaluation gate by record and replay.** Real model answers are recorded once; CI replays
them through the production pipeline for free and fails when quality drops below fixed
thresholds. A test breaks verification on purpose to prove the gate catches it.

## Ten review features, kept honest (20 Oct 2026)

**Every model output is still checked before anyone sees it.** One-click fixes must change
only the flagged line and still parse; diagrams must use a safe subset of Mermaid and name
code that is in the evidence; chat citations that do not exist are dropped. Checks found on
real model output (a `"null"` fix, line breaks inside JSON strings, a fence on the keyword's
line) became regression tests.

**Settings and guidelines come from the default branch,** so a PR cannot loosen the rules it
is reviewed by. **Learnings from GitHub need approval,** because anyone who can comment could
write one; rules that switch off a whole category are refused.

**Incremental reviews trust GitHub's compare API** and fall back to a full review whenever it
cannot say exactly what changed (rebase, force-push, 300+ files, new prompt or model).

**Static analysis runs as signals, not as comments:** tool output is evidence the model may
cite, on added lines only, so the reviewer stays one voice and the tools' noise is filtered.

**Chat streams with FastAPI's own server-sent events,** read with `fetch` in the dashboard
(EventSource cannot POST). **Analytics count a finding once,** when the model raised it.

