"""Feature extraction (T56): a PR's files and author become numbers."""

import math

import pytest

from app.modules.risk.features import (
  ChangedFile,
  extract_features,
  is_doc_file,
  is_test_file,
  size_percentile,
)


@pytest.mark.parametrize(
  ("path", "expected"),
  [
    ("tests/test_api.py", True),
    ("app/tests/helpers.py", True),  # anything inside a tests folder
    ("src/__tests__/button.js", True),
    ("spec/models/user_spec.rb", True),
    ("test_main.py", True),
    ("pkg/server_test.go", True),
    ("web/button.spec.ts", True),
    ("web/button.test.js", True),
    ("Tests/Test_Upper.py", True),  # case does not matter
    ("conftest.py", False),  # test setup, not a test
    ("app/latest.py", False),  # "test" inside a word does not count
    ("app/main.py", False),
  ],
)
def test_test_files_are_recognised(path, expected):
  assert is_test_file(path) is expected


@pytest.mark.parametrize(
  ("path", "expected"),
  [
    ("README.md", True),
    ("docs/index.html", True),  # anything in a top-level docs folder
    ("CHANGES.rst", True),
    ("LICENSE.txt", True),
    ("app/docs.py", False),  # a Python file named docs
    ("src/docs/guide.py", False),  # docs folder that is not at the top
  ],
)
def test_doc_files_are_recognised(path, expected):
  assert is_doc_file(path) is expected


def test_features_of_a_typical_pr():
  files = [ChangedFile("app/main.py", 40, 10), ChangedFile("tests/test_main.py", 20, 0)]

  features = extract_features(files, "alice", [5, 20, 70, 300])

  assert features.files_changed == 2
  assert features.lines_changed == 70
  assert features.log_lines_changed == pytest.approx(math.log1p(70))
  assert features.test_file_ratio == 0.5
  assert features.docs_only is False
  assert features.is_bot is False
  assert features.size_percentile == 0.75  # 3 of 4 PRs are 70 lines or smaller


def test_docs_only_pr():
  files = [ChangedFile("README.md", 3, 1), ChangedFile("docs/setup.md", 10, 2)]

  assert extract_features(files, "alice", []).docs_only is True


def test_mixed_pr_is_not_docs_only():
  files = [ChangedFile("README.md", 3, 1), ChangedFile("app/main.py", 1, 1)]

  assert extract_features(files, "alice", []).docs_only is False


def test_pr_without_files():
  features = extract_features([], "alice", [10, 20])

  assert (features.files_changed, features.lines_changed) == (0, 0)
  assert features.log_lines_changed == 0.0
  assert features.test_file_ratio == 0.0  # no division by zero
  assert features.docs_only is False  # all([]) is True in Python; an empty PR is not docs-only


@pytest.mark.parametrize(
  ("author", "expected"), [("dependabot[bot]", True), ("alice", False), (None, False)]
)
def test_bot_authors(author, expected):
  assert extract_features([], author, []).is_bot is expected


@pytest.mark.parametrize(
  ("lines", "expected"),
  [
    (0, 0.0),  # smaller than every PR
    (10, 0.25),  # equal counts as "at or below"
    (25, 0.5),
    (1000, 1.0),  # the largest
  ],
)
def test_size_percentile_within_the_repository(lines, expected):
  assert size_percentile(lines, [10, 20, 30, 40]) == expected


def test_size_percentile_with_ties():
  assert size_percentile(20, [10, 20, 20, 20, 50]) == 0.8


def test_size_percentile_without_history_is_typical():
  assert size_percentile(5000, []) == 0.5


def test_log_size_squashes_the_long_tail():
  small = extract_features([ChangedFile("a.py", 20, 0)], "x", []).log_lines_changed
  huge = extract_features([ChangedFile("a.py", 12_000, 0)], "x", []).log_lines_changed

  assert huge / small < 4  # 600 times the lines, but about 3 times the value
