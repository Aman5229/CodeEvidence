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
