"""The model's inputs. One definition, used both to build the training data and to score
new PRs, so training and serving can never compute a feature differently.

Every input is known when the PR is opened (no leakage): its size and files, and what the
author did *before* this PR (earlier PRs, earlier merges).
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.modules.risk.features import PullRequestFeatures

MODEL_FEATURES = (
  "log_lines_changed",
  "log_files_changed",
  "test_file_ratio",
  "docs_only",
  "is_bot",
  "size_percentile",
  "log_author_prior_prs",
  "author_prior_merge_share",
  "has_description",
)


@dataclass(frozen=True)
class AuthorHistory:
  prior_prs: int  # the author's PRs in this repository opened before this one
  prior_merged: int  # ... and merged before this one was opened


def author_history(
  created_at: datetime, earlier: Iterable[tuple[datetime, datetime | None]]
) -> AuthorHistory:
  """`earlier` holds (created_at, merged_at) of the author's PRs in the repository.

  Only merges that happened before this PR was opened count: a merge that came later was
  not known yet, and using it would leak the future into the features.
  """
  prior_prs = prior_merged = 0
  for other_created, other_merged in earlier:
    if other_created < created_at:
      prior_prs += 1
      if other_merged is not None and other_merged < created_at:
        prior_merged += 1
  return AuthorHistory(prior_prs, prior_merged)


def model_inputs(
  features: PullRequestFeatures, history: AuthorHistory, has_description: bool
) -> list[float]:
  """The values of MODEL_FEATURES, in that order."""
  return [
    features.log_lines_changed,
    math.log1p(features.files_changed),
    features.test_file_ratio,
    float(features.docs_only),
    float(features.is_bot),
    features.size_percentile,
    math.log1p(history.prior_prs),
    history.prior_merged / history.prior_prs if history.prior_prs else 0.0,
    float(has_description),
  ]
