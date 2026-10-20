"""Training data for the risk model: leak-free features, label, time order."""

from datetime import datetime, timedelta, timezone

from app.modules.ml.dataset import LABEL, PullRequestRecord, build_rows
from app.modules.ml.features import MODEL_FEATURES, AuthorHistory, author_history
from app.modules.risk.features import ChangedFile
from app.modules.risk.service import MIN_REPO_HISTORY

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def record(number: int, lines: int, *, author="alice", merged=True, day=None, repository="octo/repo"):
  created = START + timedelta(days=number if day is None else day)
  return PullRequestRecord(
    pull_request_id=number,
    repository=repository,
    author_login=author,
    created_at=created,
    merged_at=created + timedelta(hours=1) if merged else None,
    has_description=True,
    files=(ChangedFile("app/x.py", lines, 0),),
  )


def test_author_history_counts_only_what_was_known_when_the_pr_opened():
  opened = START + timedelta(days=10)
  earlier = [
    (START, START + timedelta(days=1)),  # opened and merged before: counts twice
    (START + timedelta(days=5), START + timedelta(days=20)),  # merged later: opened counts, merge does not
    (START + timedelta(days=15), None),  # opened later: does not count
  ]

  assert author_history(opened, earlier) == AuthorHistory(prior_prs=2, prior_merged=1)


def test_label_is_closed_without_merge():
  rows = build_rows([record(1, 10, merged=True), record(2, 10, merged=False)])

  assert [row[LABEL] for row in rows] == [0, 1]


def test_rows_are_oldest_first_across_repositories():
  rows = build_rows(
    [record(2, 10, repository="a/one"), record(1, 10, repository="b/two"), record(3, 10, repository="a/one")]
  )

  assert [row["pull_request_id"] for row in rows] == [1, 2, 3]


def test_size_is_compared_only_with_earlier_prs():
  # A huge PR first, then many small ones: it must not look large, nobody came before it.
  records = [record(1, 5000)] + [record(n, 10) for n in range(2, MIN_REPO_HISTORY + 3)]
  later_huge = record(MIN_REPO_HISTORY + 3, 5000)

  rows = build_rows([*records, later_huge])

  assert rows[0]["size_percentile"] == 0.5  # cold start, no history
  assert rows[-1]["size_percentile"] == 1.0  # the earlier huge PR ties it at the top
  assert rows[-2]["size_percentile"] < 1.0


def test_author_experience_grows_with_earlier_prs_only():
  rows = build_rows([record(1, 10), record(2, 10), record(3, 10, author="bob")])

  assert [row["log_author_prior_prs"] > 0 for row in rows] == [False, True, False]
  assert rows[1]["author_prior_merge_share"] == 1.0


def test_every_model_feature_is_in_each_row():
  (row,) = build_rows([record(1, 10)])

  assert set(MODEL_FEATURES) <= row.keys()
  assert row["rule_score"] >= 0
