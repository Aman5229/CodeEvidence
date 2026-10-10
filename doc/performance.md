# Performance measurements

Every number here was measured on this project, with the method written next to it,
so a result can be repeated and checked.

## Read API with and without the Redis cache

**Question:** how much does the Redis cache-aside layer cut read latency?

### Setup
- Data: `python -m scripts.seed_synthetic_data` gives 10 synthetic repositories,
  100,000 PRs and about 300,000 files. The fixed random seed makes it the same data every run.
- App: the `app` container from `docker-compose.yml`, with one uvicorn process.
- Load: Locust, `loadtests/locustfile.py`, with 50 simulated users and 0.1 to 0.5 s of
  think time each. Traffic is 40% PR lists, 20% repository stats and 40% PR details.
- Both runs use the same data, machine, traffic and duration. Only `CACHE_ENABLED` changes.

### How to run it

```bash
# 0. Data and stack
python -m scripts.seed_synthetic_data
docker compose up -d --build

# 1. Without the cache
CACHE_ENABLED=false docker compose up -d app
until curl -sf localhost:8000/health > /dev/null; do sleep 1; done   # wait until the app is up
locust -f loadtests/locustfile.py --host http://localhost:8000 \
  --headless -u 50 -r 10 -t 60s --only-summary

# 2. With the cache: empty it first and reset the hit/miss counters
CACHE_ENABLED=true docker compose up -d app
until curl -sf localhost:8000/health > /dev/null; do sleep 1; done
docker compose exec redis redis-cli FLUSHDB
locust -f loadtests/locustfile.py --host http://localhost:8000 \
  --headless -u 50 -r 10 -t 60s --only-summary
docker compose exec redis redis-cli MGET cache:hits cache:misses
```

Wait for `/health` before starting Locust: the container restarts on `up -d`, and users
that start before the app is ready fail in their setup and never send traffic.

Read the `Aggregated` row of Locust's percentile table for p50, p95 and p99. Ignore the
`setup` row, which holds the requests each simulated user makes once at start-up.
Hit rate = hits / (hits + misses).

### Results

Measured on 10 Oct 2026, 60 s per run, 50 users.

| Run | Requests/s | p50 (ms) | p95 (ms) | p99 (ms) | Failures | Hit rate |
|---|---|---|---|---|---|---|
| Without cache | 78.6 | 310 | 650 | 980 | 0 | n/a |
| With cache | 142.6 | 38 | 190 | 300 | 0 | 87.4% (7,382 hits / 1,064 misses) |
| Change | 1.8x more | 8.2x lower | 3.4x lower | 3.3x lower | | |

These are Locust's `Aggregated` rows, which also include the `setup` requests.
Per endpoint, p95 in ms, without setup:

| Endpoint | Without cache | With cache |
|---|---|---|
| `GET /pull-requests/{id}` | 470 | 180 |
| `GET /repositories/{id}/pull-requests` | 480 | 110 |
| `GET /repositories/{id}/stats` | 640 | 120 |

Machine: Intel Core i5-1235U (12 threads), 15 GB RAM. Locust and the whole stack ran on it.

### What the numbers say
- **Stats gained the most** (p95 640 to 120 ms), as expected: it is the most expensive query
  (aggregates and two `percentile_cont` sorts over 10,000 PRs per repository).
- **Throughput rose 1.8x.** Each simulated user waits for a response before its next request,
  so faster responses mean more requests in the same 60 s.
- **The cached p95 (190 ms) is still far above a single Redis read (a few ms).** Two reasons:
  12.6% of requests were misses that still query Postgres, and with 50 users on one uvicorn
  process plus Locust on the same CPU, much of the latency is time spent waiting in line, not work.
- **Without the cache, even a single-PR lookup had a p95 of 470 ms**, although it takes about
  10 ms on an idle server. Under load, requests queue behind the slow list and stats queries.
  The query tuning in M3 (indexes) targets exactly those.

### Limits of these numbers
- Locust, the app, Postgres and Redis all run on the same machine and compete for CPU.
  Absolute numbers would differ on a server; the comparison between the two runs is what counts.
- The hit rate depends on the traffic shape. Real users spread over more PRs would give a
  lower hit rate than this test, which repeats the 100 most recent PRs of each repository.
- One run of each lasts 60 s. Repeating the runs shows how much the numbers vary.

## Query plans at 100k rows (EXPLAIN ANALYZE)

**Question:** why are the uncached reads slow, and which indexes would help?

### Setup
- The same synthetic data: 100,302 PRs and 302,463 files. Repository 12 has 10,000 PRs.
- `ANALYZE;` was run first so the planner's statistics were current after the bulk load.
- Each query is the exact SQL the endpoint sends (captured from SQLAlchemy), run with
  `EXPLAIN (ANALYZE, BUFFERS)`. The only change is `SELECT *` instead of the column list.
- Indexes at that point: only those created by primary keys and unique constraints, including
  `pull_requests (repository_id, github_pr_id)` and `pull_request_files (pull_request_id, path)`.

### Results (measured 10 Oct 2026)

| # | Query | Plan | Execution time |
|---|---|---|---|
| Q1 | PR list, first page | Bitmap scan on `(repository_id, github_pr_id)` reads all 10,000 PRs of the repository, then a top-N sort keeps 21 | 8.3 ms |
| Q2 | PR list, `author=dev7` | Same scan, then a filter removes 9,976 rows, then a sort | 5.4 ms |
| Q3 | PR list, later page (cursor) | Same scan, the cursor condition removes 4,936 rows as a filter, then a sort | 6.3 ms |
| Q4 | Repository stats | Sequential scan of all 302,463 file rows, hash joins and an aggregate | 141 ms |
| Q5 | PR detail, file lookup | Index scan on `(pull_request_id, path)` | 0.05 ms |

### Findings
- **Q1 to Q3 read a whole repository's PRs to return 21.** The existing index finds the
  repository's rows but not in `created_at, id` order, so every page sorts 10,000 rows.
  A composite index on `(repository_id, created_at DESC, id DESC)` would let Postgres read
  the rows already in order, stop after 21, and use the cursor condition as a range.
- **Q4 (stats) is the slowest query, and an index will not fix it.** It needs about 10% of the
  file rows, and at that fraction a sequential scan is cheaper than 10,000 index lookups.
  Removing the cost would mean storing each PR's line totals on the PR row at ingest.
  Until then, the cache covers it.
- **Q5 shows that a separate index on `pull_request_files.pull_request_id` is not needed.**
  The unique index `(pull_request_id, path)` starts with that column, and Postgres already uses it.
- Single queries take 5 to 8 ms, while the load test without the cache had a p95 of 470 ms
  or more. Most of that latency was queueing for one app process. Faster queries still help,
  because each request holds a worker for less time.

### After adding `ix_pull_requests_repository_id_created_at_id` (measured 10 Oct 2026)

Migration `9c015e0e8c5f` adds a B-tree index on `pull_requests (repository_id, created_at, id)`.

| # | Query | Before | After | Plan after |
|---|---|---|---|---|
| Q1 | PR list, first page | 8.3 ms | 0.23 ms | Index Scan Backward: reads 21 rows, no sort |
| Q3 | PR list, later page (cursor) | 6.3 ms | 0.18 ms | The cursor becomes a range in the index |
| - | PR list, `status=open` | - | 0.39 ms | Index Scan Backward, filters 187 rows until 21 match |
| Q2 | PR list, `author=dev7` | 5.4 ms | 5.1 ms | Unchanged: the planner keeps the old plan |

- The index is ascending, and Postgres reads it backward for `ORDER BY created_at DESC, id DESC`.
  A B-tree can be read in both directions; `DESC` in an index only matters for mixed directions.
- Q2 is unchanged because the author is rare (24 of 10,000 PRs). Walking the new index would
  check almost the whole repository, so Postgres keeps the bitmap scan and sort. An index on
  `(repository_id, author_login, created_at, id)` would fix it. It was not added: 5 ms is
  acceptable at this size, and every index slows every PR insert and update.
- Not added: an index on `merged_at` (about 31% of PRs are merged, not selective enough to beat
  a scan) and on `pull_request_files.pull_request_id` (already covered by the unique index).

## Load test after the index, and where the time really goes

**Question:** does the list index improve end-to-end latency without the cache?

Same Locust workload as above (50 users, 60 s, cache off), measured 10 Oct 2026.

| Run (cache off) | Requests/s | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| Before the index (from the first table) | 78.6 | 310 | 650 | 980 | 0 |
| After the index, 1 app process | 73.3 | 350 | 760 | 1,100 | 0 |
| After the index, 4 app processes (experiment) | 129.6 | 47 | 280 | 420 | 0 |

**The index made the list query 36x faster but did not improve end-to-end latency.**
The difference between the first two rows is within run-to-run noise. Samples taken
during the run showed why:

| Signal (during load, 1 process) | Value |
|---|---|
| App container CPU | about 115% |
| Postgres connections checked out by the app | 15 of 15 (the whole pool) |
| ...actually running a query | 2 to 4 |
| ...`idle in transaction` (held while Python builds the response) | 10 to 13 |

- **The bottleneck was the single app process's CPU.** Python runs one thread at a time
  per process (the GIL), so one process can do about one core of Python work: ORM objects,
  Pydantic validation, JSON. Faster queries do not help when requests wait for the CPU.
- **The connection pool was full, but a bigger pool would not help.** Most of the held
  connections were idle while Python worked on the response.
- **The experiment confirmed it.** With 4 uvicorn worker processes on the same machine,
  still without the cache, p95 fell from 760 to 280 ms and throughput rose from 73 to
  130 requests/s. Repository stats stays the slowest endpoint (p95 430 ms), because it is
  limited by the database (see Q4).
- The number of worker processes is a deployment setting and is left for the deploy
  milestone. The experiment did not change `docker-compose.yml`. It used
  `docker compose run ... uvicorn app.main:app --workers 4`.

## Connection pool and timeouts

Settings in `app/db/session.py` and `app/db/redis.py`:

| Setting | Value | Why |
|---|---|---|
| `pool_size` | 5 | Connections kept open per app process. The load test showed 2 to 4 connections busy in Postgres at a time, so more would not raise throughput. |
| `max_overflow` | 10 | Up to 15 per process during bursts. With 4 processes that is 60, within Postgres's `max_connections` of 100, which leaves room for workers and migrations. |
| `pool_timeout` | 10 s (default 30 s) | A request that cannot get a connection fails after 10 s instead of hanging for 30 s. |
| `pool_pre_ping` | on | Each connection is checked before use, so the first requests after a Postgres restart do not fail on dead connections. |
| `connect_timeout` | 5 s | Opening a connection to an unreachable database fails fast. |
| `statement_timeout` | 10 s | Postgres cancels any query running longer than 10 s, so one runaway query cannot hold a connection forever. The slowest query today (stats) takes about 0.15 s. |
| Redis `socket_connect_timeout`, `socket_timeout` | 2 s | Without them, a stuck Redis would block requests with no limit. |

`tests/integration/test_connection_settings.py` checks that these settings reach the
real connections.

Each request holds its connection for the whole request, including the time Python spends
building the response, because the session lives as long as the request. That is why
connections show `idle in transaction`. It is fine at this size. If the pool becomes the
limit later, the fix is to close the session before serializing, not to enlarge the pool.
