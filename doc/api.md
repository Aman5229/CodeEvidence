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
  { "error": { "code": "not_found", "message": "Repository 99 not found" } }
  - 404 means that id does not exist.
  - 400 means the request is wrong (for example a broken bookmark).
  - 422 means a value has the wrong type (for example limit=abc).

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

### 5. GET /repositories/{repository_id}/stats
Returns: total_prs, merged_prs, merge_rate, bot_prs, bot_share, median_lines_changed, median_hours_to_close.
(The median is the middle value when you sort all the numbers.)