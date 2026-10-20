# Pull request risk score (rules, version `rules-v1`)

Every PR gets a score from 0 to 100, a level (low, medium, high) and the reasons behind it.
The worker computes it right after the PR's files are synced, and
`GET /pull-requests/{id}/risk` returns it. This version uses hand-picked rules; it is the
baseline that a trained model has to beat. The trained model ([ml.md](ml.md)) is served next
to it in the same answer.

## Features (`app/modules/risk/features.py`)

| Feature | How it is computed | Why |
|---|---|---|
| `files_changed` | number of changed files | more files, more places to break |
| `lines_changed` | additions + deletions over all files | bigger changes are harder to review |
| `log_lines_changed` | `log(1 + lines_changed)` | sizes are very skewed (EDA: median 22, max 12,631); the log keeps one huge PR from dominating |
| `test_file_ratio` | share of changed files that are tests (`tests/`, `test_*.py`, `*_test.go`, `*.spec.ts`, ...) | code changed together with tests is safer |
| `docs_only` | every changed file is documentation (`.md`, `.rst`, `.txt`, `.adoc`, or under a top-level `docs/`) | documentation cannot break running code |
| `is_bot` | author login ends with `[bot]` | bot PRs are a separate population (EDA: median 6 lines vs 27 for people) |
| `size_percentile` | share of the repository's scored PRs at or below this PR's size | 200 lines is big in one repository and normal in another (EDA: medians differ about 3x between repositories) |

**No leakage:** only information known when the PR is opened is used. Merge time, close time
and review outcome are never features, so the same features can train a model that predicts
those outcomes later.

**Cold start:** until a repository has 20 other scored PRs, `size_percentile` is set to 0.5
(typical), because the first PRs of a repository would otherwise always count as its largest.

## Rules (`app/modules/risk/score.py`)

Start at 10 points, add or remove points for each rule that applies, keep the result between
0 and 100.

| Rule | Points | Reason code |
|---|---|---|
| Only documentation changed | score is 0, nothing else applies | `docs_only` |
| Among the largest 10% of the repository's PRs | +30 | `very_large_for_repo` |
| Among the largest 25% (but not 10%) | +15 | `large_for_repo` |
| 500 or more lines changed | +15 | `many_lines` |
| 20 or more files changed | +15 | `many_files` |
| 10 to 19 files changed | +8 | `several_files` |
| No test files, and 50 or more lines changed | +20 | `no_tests` |
| At least 30% of the changed files are tests | -10 | `has_tests` |
| Opened by a bot | -10 | `bot_author` |
| None of the above | 0 | `typical_change` |

Levels: low below 30, medium from 30, high from 60. The highest possible score is 90
(very large for its repository, 500+ lines, 20+ files, no tests). Every score lists at least
one reason, and the points of the reasons add up to the score.

## Recomputing scores

New PRs are scored automatically. To score PRs stored earlier, or after changing the rules:

```bash
python -m scripts.score_pull_requests                  # every repository
python -m scripts.score_pull_requests pallets/flask    # one repository
```

Rescoring uses the complete set of the repository's PRs as the size baseline, so every PR is
compared with the same distribution.

## Validation on real PRs

*Pending: needs the real backfilled data in the database (the stack is being set up on a new
machine).* The plan for this section:

1. Score the 5 real repositories (about 300 PRs).
2. Distribution: how many PRs are low, medium and high, per repository.
3. Read the 10 highest-scoring PRs and judge each one: is it really a risky change, or a
   false alarm? Note the pattern behind every false alarm.
4. Sanity checks: docs-only PRs score 0; bot PRs score low; the repository-relative size
   flags the PRs the EDA found to be outliers.

## Limitations

- **The weights are guesses.** Nothing was learned from data; they encode common sense
  about review risk. A trained model (next milestone) should replace them, and must be
  compared against this score.
- **"Risk" has no ground truth here.** There is no label saying which PRs caused bugs, so the
  score cannot yet be called accurate or inaccurate, only reasonable.
- **Paths are matched by name only.** A test file in an unusual place is not recognised as a
  test, and a code file under `docs/` counts as documentation.
- **Size is not the same as risk.** A one-line change to authentication code can be riskier
  than a 500-line refactor. The features say nothing about *what* changed; that is the job of
  the code analysis and AI review milestones.
- **Bots get fewer points.** Dependency updates are usually routine, but a major-version bump
  can break things. The rule assumes the common case.
- **The baseline grows over time.** A PR scored early in a repository's history was compared
  with fewer PRs than one scored later. Rescoring the repository fixes this.

## How to evaluate it with real labels

A score is only useful if it agrees with outcomes. With labels, the evaluation would be:

1. **Pick a label known after the fact**, for example "closed without being merged", "reverted
   within 30 days", or "followed by a bug-fix PR touching the same files". Each answers a
   slightly different question; the model milestone chooses one and explains why.
2. **Split by time**, not at random: score older PRs, evaluate on newer ones. A random split
   would let the future leak into the past.
3. **Measure ranking quality**, because the score is used to order PRs: ROC-AUC, and
   PR-AUC, which is more informative when risky PRs are rare. Also look at precision among
   the top 10% of scores: of the PRs flagged as riskiest, how many really were?
4. **Compare against simple baselines**: lines changed alone, and a constant score. If the
   rules do not beat "bigger PRs are riskier", the rules add nothing.
5. **Check calibration** if the score is ever read as a probability: do PRs scored 70 turn
   out bad about 70% of the time? This score is not a probability, and must not be read as one.
