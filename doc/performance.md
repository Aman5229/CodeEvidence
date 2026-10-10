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
