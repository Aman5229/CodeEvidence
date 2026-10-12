# Operating CodeEvidence: logs, metrics, health, access

## Logs

Every line from the app and the worker, including library logs (uvicorn, Celery, httpx), is
one JSON object on stdout:

```json
{"ts": "2026-10-12T16:50:06.163+00:00", "level": "INFO", "logger": "app.jobs", "msg": "Job started",
 "request_id": "trace-docker-1", "delivery_id": "d-42", "job_id": 3700, "job_type": "sync_pr_files", "attempt": 1}
```

| Field | Set by | Meaning |
|---|---|---|
| `request_id` | every HTTP request | Taken from the `X-Request-ID` header if it is safe (letters, digits, `.` `_` `-`, at most 64 characters), otherwise generated. Returned in the response's `X-Request-ID` header. |
| `delivery_id` | the webhook | GitHub's delivery id |
| `job_id` | the worker | The `job_runs` row of the running job |

**Correlation.** A job's message carries the `request_id` and `delivery_id` of the request
that queued it, and the worker sets them before running the job. Jobs queued by a job (the
file sync after `process_event`) inherit them. One id therefore finds a webhook's request
and every job it caused, across the app and worker containers:

```bash
docker compose logs --no-log-prefix app worker | grep '"request_id": "trace-docker-1"'
```

Each request also writes one access line (`logger: app.access`) with `status`, `route`
(the route template, for example `/repositories/{repository_id}`) and `duration_ms`.
Set the level with `LOG_LEVEL` (default `INFO`).

## Metrics

`GET /metrics` returns the Prometheus text format.

| Metric | Type | Source |
|---|---|---|
| `http_request_duration_seconds{method, route, status}` | histogram | measured in the app process |
| `codeevidence_jobs{job_type, status}` | gauge | `job_runs` in Postgres; `status="failed"` are the dead letters |
| `codeevidence_queue_depth` | gauge | length of the Celery queue in Redis |
| `codeevidence_cache_lookups_total{result}` | counter | cache hit and miss counters in Redis |
| `codeevidence_github_circuit_state{state}` | gauge | 1 for the circuit breaker's current state |

Jobs, queue, cache and breaker are read at scrape time from where they live, because the
worker runs in other processes: counters kept in the app's memory would never see its jobs.
Each source is read separately, so one that is down does not hide the others. The `route`
label is the template, never the raw path, and unknown paths share `route="unmatched"`, so
the number of label values stays small.

Useful queries: p95 latency per route
`histogram_quantile(0.95, sum by (le, route) (rate(http_request_duration_seconds_bucket[5m])))`;
cache hit rate `rate(codeevidence_cache_lookups_total{result="hit"}[5m]) / ignoring(result) sum(rate(codeevidence_cache_lookups_total[5m]))`.

## Health checks

| Endpoint | Meaning | Use it for |
|---|---|---|
| `GET /health` | **Liveness**: the process is running. Checks nothing else. | Restarting a stuck process. It must not depend on the database: restarting the app does not fix a database outage. |
| `GET /health/ready` | **Readiness**: database, cache and queue all answer. 503 with the failing check otherwise. | Taking a process out of a load balancer until its dependencies are back. |

```json
{"status": "not_ready", "checks": {"database": "unavailable", "cache": "ok", "queue": "ok"}}
```

Failure details go to the logs, not to the caller.

## Access: API keys and rate limits

The read API (`/repositories`, `/pull-requests`, `/events`, `/jobs`) needs an API key in the
`X-API-Key` header. Open: `/health`, `/health/ready`, `/metrics`, and the webhook, which is
authenticated by its HMAC signature instead.

```bash
python -m scripts.create_api_key "my laptop"                      # on the host
docker compose exec app python -m scripts.create_api_key "my laptop"   # or in the container
```

The key is printed once and stored only as a SHA-256 hash. Keys are 32 random bytes, so a
plain hash is enough: there is nothing to guess, unlike a password. A missing, unknown or
revoked key gets 401.

**Rate limit:** a token bucket per key in Redis. Up to `RATE_LIMIT_CAPACITY` requests at once
(default 60), refilled at `RATE_LIMIT_PER_SECOND` (default 10). Over the limit: 429 with a
`Retry-After` header. The check runs as one Lua script inside Redis, so it is atomic across
app processes and uses Redis's clock. If Redis is down, requests are allowed (fail open):
losing the rate limit for a while is better than losing the API.

Measured on 12 Oct 2026: a burst of 100 requests, 20 in parallel, with the defaults gave
71 × 200 (the 60-request burst plus tokens refilled during it) and 29 × 429.
