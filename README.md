# CodeEvidence

[![CI](https://github.com/Aman5229/CodeEvidence/actions/workflows/ci.yml/badge.svg)](https://github.com/Aman5229/CodeEvidence/actions/workflows/ci.yml)

A repository-aware, evaluation-driven AI code review platform.

> **Current scope:** CodeEvidence receives GitHub pull request webhooks, stores PRs and
> their changed files, scores each PR's risk (rules plus a trained model), retrieves related
> code from the repository, and writes an AI review whose every finding is checked against
> the evidence before anyone sees it. A React dashboard shows it all.

---

## What it does today

When GitHub sends a webhook, CodeEvidence:

1. **Verifies the signature** (HMAC-SHA256 with a shared secret) — rejects anything not genuinely from GitHub.
2. **Checks for duplicates** by GitHub's delivery ID — the same delivery is never processed twice.
3. **Saves the raw event first** and commits it — the original payload is never lost.
4. **Queues a background job and answers `202 Accepted`** within milliseconds, without calling GitHub.

A Celery worker then does the work in two jobs:

- **`process_event`** (database only): creates the repository if it is new, creates or updates
  the pull request, and marks the event `processed` (or `received` for events with nothing
  to process, such as `ping`).
- **`sync_pr_files`** (calls GitHub): fetches the PR's changed files (paginated, up to
  GitHub's 3,000-file limit) and replaces the stored file list.

If GitHub fails, only the file sync fails and is retried with backoff (up to 6 attempts); the
PR row is already saved. Rate limits pause every worker until GitHub's reset time, and a
circuit breaker stops calling GitHub during an outage (see [doc/background-jobs.md](doc/background-jobs.md)). Jobs that still fail become dead letters (`GET /jobs`). If the job cannot
be queued (Redis unreachable), the event is marked `failed` and the webhook returns `503`,
so the delivery can be retried with GitHub's **Redeliver** button. A redelivered failed
event is queued again.

## The product: risk, retrieval, AI review

| Part | What it does | Docs |
|---|---|---|
| Risk score | Rule-based score 0-100 with reasons, computed after each file sync | [doc/risk.md](doc/risk.md) |
| ML risk model | Predicts "closed without merge"; trained on a time split, calibrated, served next to the rules with a fallback | [doc/ml.md](doc/ml.md) |
| Code retrieval | tree-sitter chunks, local embeddings in pgvector, hybrid vector + keyword search, deterministic signals, a token-budgeted evidence bundle | [doc/retrieval.md](doc/retrieval.md) |
| AI review | Claude (or a free local model) proposes findings as JSON; verification drops anything the evidence does not support; ranked, capped, cached, cost-budgeted, injection-hardened | [doc/review.md](doc/review.md) |
| Review features | One-click fixes, repository settings and guidelines, incremental reviews, learnings from feedback, ruff/semgrep/gitleaks signals, sequence diagrams and review effort, a walkthrough comment and merge check, chat with citations (dashboard and `@codeevidence`) | [doc/review.md](doc/review.md) |
| Triage and insight | A review queue (priority, effort, suggested reviewers), analytics on review usefulness, and the blast radius of a change | [doc/api.md](doc/api.md) |
| GitHub feedback and evaluation | Idempotent inline comments on a sandbox repo, feedback capture, labelled-set metrics, a replay quality gate in CI | [doc/evaluation.md](doc/evaluation.md) |
| Dashboard | React + TypeScript over the API | [frontend/README.md](frontend/README.md) |

## API

| Method | Path | Returns |
|---|---|---|
| GET | `/repositories` | Stored repositories (cursor-paged) |
| GET | `/repositories/{id}` | One repository |
| GET | `/repositories/{id}/stats` | PR counts, merge rate, bot share, median size and time to close |
| GET | `/repositories/{id}/pull-requests` | PRs, newest first; filters: `status`, `merged`, `author`, `is_bot`, `created_after`, `created_before` |
| GET | `/pull-requests/{id}` | One PR with changed files and totals (`?include_patch=true` adds the diffs) |
| GET | `/pull-requests/{id}/risk` | Risk score 0-100 with its reasons and features, plus the ML model's prediction ([doc/risk.md](doc/risk.md)) |
| GET | `/pull-requests/{id}/review` | The latest AI review: summary, diagram, effort and verified, ranked findings with their evidence and one-click fixes |
| POST | `/pull-requests/{id}/review` | Queue an AI review (`?mode=full` to review everything; an identical earlier one is reused at no cost) |
| GET, POST | `/pull-requests/{id}/chat` | The PR's conversation; ask a question (answer streamed as server-sent events) |
| GET | `/pull-requests/{id}/impact` | Changed functions and classes, and the code that uses them |
| GET, POST | `/repositories/{id}/learnings` | Rules for future reviews (`PATCH`, `DELETE /learnings/{id}`) |
| GET | `/repositories/{id}/config` | The `.codeevidence.yaml` settings and guideline files in use |
| GET | `/review-queue` | Open PRs in the order to review them |
| GET | `/analytics` | How useful the reviews are, over time |
| POST | `/repositories/{id}/index` | Queue indexing of the repository's code for retrieval |
| POST | `/findings/{id}/feedback` | Rate a finding: `{"verdict": "useful" \| "not_useful"}` |
| POST | `/webhooks/github` | Signed GitHub webhook receiver (stores, queues, answers 202) |
| GET | `/events/{delivery_id}` | A delivery and the status of every job it started |
| GET | `/jobs` | Background jobs; by default the dead letters (`status=failed`) |
| POST | `/jobs/{id}/retry` | Queue a dead letter again |

Lists return `{"items": [...], "next_cursor": "..."}`. Send `next_cursor` back as
`cursor` to get the next page. Errors always look like
`{"error": {"code": "not_found", "message": "..."}}`.

```bash
curl -H "X-API-Key: $API_KEY" "http://localhost:8000/repositories/1/pull-requests?merged=true&limit=5"
```

The read API needs an API key (`python -m scripts.create_api_key "my laptop"`, sent as the
`X-API-Key` header) and is rate-limited per key. Logs are JSON with request, delivery and job
ids; `GET /metrics` serves Prometheus metrics; `GET /health` and `GET /health/ready` are the
liveness and readiness checks. See [doc/operations.md](doc/operations.md).

Interactive docs are served at `/docs`. The full design is in [doc/api.md](doc/api.md).

## Flow

```
GitHub webhook
      │
      ▼
POST /webhooks/github ── bad headers → 400 · bad signature → 401 · bad JSON → 400
      │
      ▼
Already handled? ── yes → 200 duplicate_ignored
      │ no (or previously failed)
      ▼
Save raw event (commit, status=received)
      │
      ▼
Queue process_event(event_id) ── Redis down → event failed, 503 (retry via Redeliver)
      │
      ▼
202 Accepted
                 ── worker (background) ──────────────────────────────────────────
                 process_event:  upsert repository → upsert pull request → processed
                                 → clear cached PR data → queue sync_pr_files(pr_id)
                 sync_pr_files:  fetch changed files from GitHub → replace stored files
                                 → clear cached PR data
```

## Project structure

```
app/
  main.py                      # FastAPI app, registers routers
  worker.py                    # Celery app: broker settings (late acks, prefetch 1)
  jobs.py                      # background jobs run by the worker
  core/                        # settings, time helpers, cursor pagination
  db/                          # engine/session, SQLAlchemy models
  schemas/                     # Pydantic response models (the API's output shapes)
  api/routes/                  # thin HTTP layer: health, webhooks, repositories, pull requests
  integrations/github/         # the only code that talks to GitHub: signature, API client, guard
  modules/ingestion/           # ingestion logic: event store, repo/PR/file sync, service flow
  modules/risk/                # rule-based risk score
  modules/ml/                  # ML risk model: dataset, training, serving, drift
  modules/code/                # diff parser, filters, chunking, embeddings, retrieval, evidence
  modules/review/              # LLM provider, prompts, verification, ranking, publishing, evaluation
frontend/                      # React + TypeScript dashboard (Vite)
eval/                          # recorded review cases and quality thresholds (CI gate)
models/                        # the trained risk model file
doc/                           # API design, measurements, decision log, ML/retrieval/review docs
migrations/                    # Alembic schema migrations
scripts/                       # dev tools and sample payloads (not app code)
tests/
  unit/                        # pure functions, no database
  integration/                 # API and webhook flow against a test database + fake GitHub
.github/workflows/ci.yml       # CI: ruff + pytest on a Postgres service
Dockerfile, docker-compose.yml # container build and local stack (app, worker, Postgres, Redis)
```

## Data model

| Table | Purpose |
|---|---|
| `repositories` | One row per GitHub repository |
| `pull_requests` | One row per PR, unique per repository, updated as the PR changes |
| `pull_request_files` | Changed files of a PR: path, status, additions/deletions, patch |
| `github_events` | Every accepted webhook: raw payload, status, error message, timestamps |
| `job_runs` | Every background job: status, attempts, last error (failed rows are dead letters) |
| `api_keys` | API keys, stored as SHA-256 hashes |
| `pull_request_risks` | Each PR's features, rule score with reasons, and the model's prediction |
| `file_blobs` | File contents by blob SHA (fetched once) |
| `code_chunks` | Functions and classes of indexed repositories, with embeddings (pgvector) and full-text search |
| `reviews` | AI review runs: prompt version, model, tokens, cost, latency, cache key, evidence |
| `review_findings` | Every proposed finding, kept or dropped (with the reason), rank and GitHub comment id |
| `finding_feedback` | Reactions, replies, resolved threads and dashboard votes on findings |

## Tech stack

Python 3.12 · FastAPI · SQLAlchemy 2.x · PostgreSQL 16 + pgvector · Redis 7 · Celery · Alembic · httpx · pytest ·
scikit-learn · tree-sitter · sentence-transformers · Anthropic Claude · React + TypeScript (Vite, TanStack Query)

---

## Quickstart (Docker)

The fastest way to run it. Needs only Docker.

```bash
git clone https://github.com/Aman5229/CodeEvidence.git
cd CodeEvidence
cp .env.example .env          # then set GITHUB_WEBHOOK_SECRET and GITHUB_TOKEN
docker compose up --build
```

This starts PostgreSQL and Redis, waits until both are healthy, applies migrations,
serves the API on port 8000 and starts a Celery worker for background jobs.

- Worker check: `docker compose exec worker celery -A app.worker call app.jobs.ping`, then
  `docker compose logs worker --tail 5` shows `Task app.jobs.ping[...] succeeded ... 'pong'`

- Health check: `curl http://localhost:8000/health` → `{"status":"ok"}`
- Interactive API docs: http://localhost:8000/docs

Stop with `Ctrl+C`. `docker compose down -v` also deletes the database volume.

## Local development (without Docker for the app)

### 1. Requirements

- Python 3.11–3.12
- Docker (for PostgreSQL and Redis)
- A GitHub personal access token with read access to pull requests

### 2. Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ".[embeddings]"   # optional: the local embedding model (large: PyTorch)
```

### 3. Configure

```bash
cp .env.example .env
```

Then fill in `.env`:

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string for the cache, e.g. `redis://localhost:6380/0` |
| `CELERY_BROKER_URL` | Redis for the job queue, a separate database: `redis://localhost:6380/1` |
| `GITHUB_WEBHOOK_SECRET` | Shared secret, must match the one set on the GitHub webhook |
| `GITHUB_TOKEN` | Token used to fetch PR files from the GitHub API |
| `ANTHROPIC_API_KEY` | *(optional)* For AI reviews; `LLM_PROVIDER=fake` runs without one |
| `PUBLISH_REPOSITORIES` | *(optional)* The only repositories reviews are posted to, e.g. your sandbox |
| `REVIEW_ON_SYNC`, `REVIEW_BUDGET_USD` | *(optional)* Review every synced PR automatically; spending cap per review |
| `EMBEDDING_PROVIDER` | *(optional)* `local` (default) or `fake` |
| `TEST_DATABASE_URL` | *(optional)* Test database; defaults to `codeevidence_test` on port 5433 |
| `TEST_REDIS_URL` | *(optional)* Test Redis; defaults to database 15 on port 6380, so tests never touch the app's cache |

**Secrets:** `.env` is listed in `.gitignore` and must never be committed. Only
`.env.example`, with placeholder values, lives in git. CI uses dummy values
(`ci-secret`, `ci-token`) because tests use a fake GitHub client. If a token is
ever exposed, revoke it immediately in GitHub → Settings → Developer settings →
Personal access tokens, then create a new one.

### 4. Start the database and apply migrations

```bash
docker compose up -d
alembic upgrade head
```

### 5. Run the API

```bash
uvicorn app.main:app --reload
```

Check it: `curl http://localhost:8000/health` → `{"status":"ok"}`

---

## Running tests

Create the test database once (tests never touch your real data):

```bash
docker compose exec postgres createdb -U codeevidence codeevidence_test
```

Then:

```bash
pytest -v
```

Integration tests use a **fake GitHub client**, so they need no network access or token.

## Sending a test webhook locally

```bash
SIG=$(python -c "
import hmac, hashlib
from app.core.config import settings
body = open('scripts/sample_payloads/test_pr_payload.json', 'rb').read()
print(hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest())
")

curl -i -X POST http://localhost:8000/webhooks/github \
  -H "X-GitHub-Delivery: local-test-001" \
  -H "X-GitHub-Event: pull_request" \
  -H "X-Hub-Signature-256: sha256=$SIG" \
  -H "Content-Type: application/json" \
  --data-binary @scripts/sample_payloads/test_pr_payload.json
```

Use `--data-binary` (not `-d`): the signature must be computed over the exact bytes sent.

## Receiving real GitHub webhooks

GitHub must be able to reach your machine, so expose port 8000 with a tunnel
(for example smee.io or ngrok), then in the repository's
**Settings → Webhooks → Add webhook**:

- **Payload URL:** `<your-tunnel-url>/webhooks/github`
- **Content type:** `application/json`
- **Secret:** the same value as `GITHUB_WEBHOOK_SECRET`
- **Events:** *Pull requests*; for feedback on posted reviews also *Pull request review
  comments* and *Pull request review threads*

## Synthetic data for load testing

The real dataset (about 300 PRs) is too small for meaningful performance numbers,
so a script generates synthetic data with realistic shapes: right-skewed PR sizes,
about 10% bot authors, 10% open PRs and about 35% of closed PRs merged.

```bash
python -m scripts.seed_synthetic_data                              # 10 repos x 10,000 PRs (~300k files)
python -m scripts.seed_synthetic_data --repos 2 --prs-per-repo 500
```

Synthetic repositories are owned by `synthetic`. Each run deletes the previous
synthetic rows first and uses a fixed random seed, so the data is identical on
every run. Real repositories are never touched.

---

## Known limitations

- **No transactional outbox.** If the app crashes between committing an event and queueing its job, the job stays `queued` and never runs. Such jobs can be found with `GET /jobs?status=queued`, but there is no one-click recovery for them yet. See [doc/background-jobs.md](doc/background-jobs.md).
- **Only `pull_request` events and replies or resolutions on our review comments are processed.** Other events are stored as `received`.
- **Repository metadata is not refreshed** after the first insert (e.g. a renamed repo keeps its old name).
- `patch_truncated` and `is_stale` on files are placeholders, not yet computed.
- **One-click fixes are checked for syntax, not imports or meaning:** a fix can use a module the file does not import.
- **Impact finds uses inside functions and classes** of the indexed default branch, by name: module-level uses are missed, and same-named functions can match.
- **Small local models** (qwen2.5-coder 7B) skip citations at times and draw a sequence diagram for about half the PRs; a larger model is expected to do better.
