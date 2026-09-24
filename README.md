# CodeEvidence

A repository-aware, evaluation-driven AI code review platform.

> **Current scope:** CodeEvidence securely receives GitHub pull request webhooks
> and stores reliable, queryable review input: repositories, pull requests,
> changed files and the raw events themselves.

---

## What it does today

When GitHub sends a webhook, CodeEvidence:

1. **Verifies the signature** (HMAC-SHA256 with a shared secret) — rejects anything not genuinely from GitHub.
2. **Checks for duplicates** by GitHub's delivery ID — the same delivery is never processed twice.
3. **Saves the raw event first**, in its own transaction — the original payload is never lost, even if processing fails.
4. **Processes `pull_request` events:**
   - creates the repository if it is new
   - creates or updates the pull request (new commits, title changes, merge/close)
   - fetches the PR's changed files from the GitHub API (paginated, up to GitHub's 3000-file limit) and replaces the stored file list
5. **Records the outcome** on the event: `processed` (with `processed_at`), `received` (nothing to process, e.g. `ping`), or `failed` (with `error_message`).

If processing fails, all partial work is rolled back, the event is kept as `failed`,
and the endpoint returns `500` so the delivery can be retried with GitHub's
**Redeliver** button. A redelivered failed event is processed again.

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
Save raw event (commit #1, status=received)
      │
      ▼
Upsert repository → upsert pull request → sync changed files (GitHub API)
      │
  ┌───┴──────────────┐
success            failure
commit #2          rollback, status=failed + error_message
processed          → 500 (retry via Redeliver)
```

## Project structure

```
app/
  main.py                      # FastAPI app, registers routers
  core/                        # settings, time helpers
  db/                          # engine/session, SQLAlchemy models
  api/routes/                  # thin HTTP layer: health, webhooks
  integrations/github/         # the only code that talks to GitHub: signature, API client
  modules/ingestion/           # ingestion logic: event store, repo/PR/file sync, service flow
migrations/                    # Alembic schema migrations
scripts/                       # dev tools and sample payloads (not app code)
tests/
  unit/                        # pure functions, no database
  integration/                 # full webhook flow against a test database + fake GitHub
```

## Data model

| Table | Purpose |
|---|---|
| `repositories` | One row per GitHub repository |
| `pull_requests` | One row per PR, unique per repository, updated as the PR changes |
| `pull_request_files` | Changed files of a PR: path, status, additions/deletions, patch |
| `github_events` | Every accepted webhook: raw payload, status, error message, timestamps |

## Tech stack

Python 3.10+ · FastAPI · SQLAlchemy 2.x · PostgreSQL 16 (Docker) · Alembic · httpx · pytest

---

## Getting started

### 1. Requirements

- Python 3.10–3.12
- Docker (for PostgreSQL)
- A GitHub personal access token with read access to pull requests

### 2. Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Configure

```bash
cp .env.example .env
```

Then fill in `.env`:

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `GITHUB_WEBHOOK_SECRET` | Shared secret, must match the one set on the GitHub webhook |
| `GITHUB_TOKEN` | Token used to fetch PR files from the GitHub API |
| `TEST_DATABASE_URL` | *(optional)* Test database; defaults to `codeevidence_test` on port 5433 |

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
- **Events:** *Pull requests*

---

## Known limitations

- **Processing is synchronous** inside the request, so the webhook responds only after files are fetched from GitHub.
- **Only `pull_request` events are processed.** Other events are stored as `received`.
- **Repository metadata is not refreshed** after the first insert (e.g. a renamed repo keeps its old name).
- `patch_truncated` and `is_stale` on files are placeholders, not yet computed.
- Two simultaneous deliveries with the same ID could race on the unique constraint; rare in practice.
