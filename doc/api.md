# CodeEvidence API plan (version 1)

We write this plan before the code, so we know what we are building.

## Rules for every endpoint
- Data goes in and out as JSON (a plain-text format for data).
- Dates look like 2026-10-12T09:30:00Z.
- The ids you see are our own database numbers, not GitHub's numbers.
- A list comes back in pages, in this shape:
  { "items": [ ... ], "next_cursor": "abc123" }
  - "items" is the results for this page.
  - "next_cursor" is a bookmark. Send it back to get the next page. When it is null, there are no more pages.
- Options for lists: limit (items per page, default 20, maximum 100) and cursor (the bookmark).
- When something goes wrong, the answer always has this shape:
  { "error": { "code": "not_found", "message": "Repository not found" } }
  - "code" is for programs and never changes. "message" is for people and may be reworded.

  | Status | code               | When |
  |--------|--------------------|------|
  | 400    | bad_request        | The request is wrong, e.g. a broken cursor or a missing webhook header |
  | 401    | unauthorized       | The webhook signature does not match |
  | 404    | not_found          | That id does not exist, or the URL does not exist |
  | 405    | method_not_allowed | Wrong HTTP method; the Allow header lists the right one |
  | 422    | validation_error   | A value has the wrong type or range, e.g. limit=abc or limit=0 |
  | 500    | internal_error     | A bug on our side. The details are logged and never sent to the client |

  For 422, the message lists every bad value as "where.name: problem", separated by "; ",
  e.g. "query.limit: Input should be greater than or equal to 1; query.status: Input should be 'open' or 'closed'".

## Endpoints

### 1. GET /repositories
Returns the stored repositories, in id order.
Each item has: id, full_name, owner, default_branch, html_url, is_private, last_synced_at.

### 2. GET /repositories/{repository_id}
Returns one repository with the same fields. Returns 404 if the id does not exist.

### 3. GET /repositories/{repository_id}/pull-requests
Returns the pull requests of one repository, newest first.
Options (all optional, and they can be combined):
- status: for example open or closed
- merged: true = only merged PRs, false = only PRs that were not merged
- author: only PRs by this GitHub username
- is_bot: true = only bot authors, false = only humans
- created_after and created_before: only PRs created in that date range
Each item has: id, number, title, author_login, is_bot, status, is_merged, created_at, closed_at, merged_at.
(is_bot is true when the author name ends with [bot]. is_merged is true when merged_at has a value.)

### 4. GET /pull-requests/{pull_request_id}
Returns one pull request with more detail: body, base_branch, head_branch, head_sha, updated_at,
the list of changed files (path, previous_path, status, additions, deletions, changes),
and totals (files_changed, additions, deletions, lines_changed).
The code changes themselves (patches) are left out unless you add ?include_patch=true.
The answer is cached in Redis for up to 5 minutes (one entry with patches, one without),
so a change to the PR can take up to 5 minutes to show.

### 5. GET /repositories/{repository_id}/stats
Returns: repository_id, total_prs, closed_prs, merged_prs, merge_rate, bot_prs, bot_share,
median_lines_changed, median_hours_to_close. Returns 404 if the repository id does not exist.

How each number is worked out:
- closed_prs: PRs whose status is closed. Merged PRs count as closed too, as on GitHub.
- merge_rate = merged_prs / closed_prs. Open PRs are left out because they are not decided yet.
- bot_share = bot_prs / total_prs (a bot is an author whose name ends with [bot]).
- median_lines_changed: the median of (additions + deletions) per PR. A PR with no files counts as 0 lines.
- median_hours_to_close: the median time from created to closed, using closed PRs only.
- The median is the middle value when you sort all the numbers. With an even count it is the
  average of the two middle values (SQL percentile_cont(0.5)), the same as pandas' median().
- If there is nothing to divide by or nothing to take a median of, the value is null, not 0.
  For example, a repository with only open PRs has merge_rate null. That means "not known yet",
  while 0 would claim that nothing was ever merged.