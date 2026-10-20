"""Fake embeddings, rank fusion, retrieval metrics, signals and the evidence budget."""

import math

import pytest

from app.modules.code.diff import parse_patch
from app.modules.code.embeddings import FakeEmbedder
from app.modules.code.evidence import build_bundle, estimate_tokens
from app.modules.code.retrieval import (
  RetrievedChunk,
  keyword_query,
  recall_at_k,
  reciprocal_rank,
  reciprocal_rank_fusion,
)
from app.modules.code.signals import FileDiff, detect_signals


def cosine(a, b):
  return sum(x * y for x, y in zip(a, b, strict=True))


def diff(path: str, added: list[str], removed: int = 0) -> FileDiff:
  body = "\n".join("+" + line for line in added)
  patch = f"@@ -1,{removed} +1,{len(added)} @@\n{body}"
  return FileDiff(path, "modified", len(added), removed, tuple(parse_patch(patch)))


# ---------- fake embedder ----------

def test_fake_embeddings_are_stable_unit_vectors():
  first, again = FakeEmbedder().embed(["def get_user(id): ..."]), FakeEmbedder().embed(["def get_user(id): ..."])

  assert first == again
  assert len(first[0]) == 384
  assert math.isclose(math.sqrt(cosine(first[0], first[0])), 1.0)


def test_fake_embeddings_put_shared_words_closer():
  user, user_again, invoice = FakeEmbedder().embed(["load user profile", "save user profile", "render invoice pdf"])

  assert cosine(user, user_again) > cosine(user, invoice)


def test_empty_text_still_gets_a_vector():
  (vector,) = FakeEmbedder().embed([""])

  assert any(vector)


# ---------- rank fusion and metrics ----------

def test_rank_fusion_rewards_agreement():
  fused = reciprocal_rank_fusion({"vector": [1, 2, 3], "keyword": [3, 4, 1]})

  ids = [chunk_id for chunk_id, _, _ in fused]
  assert ids[:2] == [1, 3]  # found by both
  assert dict((i, f) for i, _, f in fused)[1] == ("vector", "keyword")
  assert set(ids) == {1, 2, 3, 4}


def test_keyword_query_ors_unique_words():
  assert keyword_query("user.get_name(user)") == "user | get | name"  # Postgres splits get_name itself
  assert keyword_query("+ - ( )") is None


def test_recall_and_reciprocal_rank():
  ranked = ["a", "b", "c", "d"]

  assert recall_at_k(ranked, {"b", "z"}, 3) == 0.5
  assert reciprocal_rank(ranked, {"c"}) == pytest.approx(1 / 3)
  assert reciprocal_rank(ranked, {"z"}) == 0.0


# ---------- signals ----------

def codes(signals):
  return [signal.code for signal in signals]


@pytest.mark.parametrize(
  ("line", "code"),
  [
    ("result = eval(user_input)", "dynamic_code_execution"),
    ("subprocess.run(cmd, shell=True)", "shell_injection_risk"),
    ("data = pickle.loads(blob)", "unsafe_deserialization"),
    ("config = yaml.load(text)", "unsafe_deserialization"),
    ("requests.get(url, verify=False)", "tls_verification_disabled"),
    ('cursor.execute(f"SELECT * FROM t WHERE id = {id}")', "sql_built_from_strings"),
    ('API_KEY = "sk_live_abcdefgh12345"', "hardcoded_secret"),
    ("except:", "bare_except"),
    ("breakpoint()", "debugger_left_in"),
    ("# TODO: handle errors", "todo_added"),
  ],
)
def test_risky_patterns_in_added_lines(line, code):
  (signal,) = detect_signals([diff("app/x.py", [line])])

  assert signal.code == code
  assert (signal.path, signal.line) == ("app/x.py", 1)


def test_safe_variants_are_not_flagged():
  safe = ["config = yaml.load(text, Loader=yaml.SafeLoader)", "cursor.execute(sql, (id,))", "except ValueError:"]

  assert detect_signals([diff("app/x.py", safe)]) == []


def test_removed_lines_and_non_code_files_are_not_scanned():
  patch = "@@ -1,1 +1,0 @@\n-x = eval(y)"
  removed = FileDiff("app/x.py", "modified", 0, 1, tuple(parse_patch(patch)))

  assert detect_signals([removed, diff("notes.md", ["eval(x)"])]) == []


def test_dependency_change_and_missing_tests():
  signals = detect_signals([diff("requirements.txt", ["httpx==0.28"]), diff("app/core.py", ["x = 1"] * 60)])

  assert codes(signals) == ["dependency_change", "missing_tests"]


def test_tests_in_the_pr_mean_no_missing_tests_signal():
  assert detect_signals([diff("app/core.py", ["x = 1"] * 60), diff("tests/test_core.py", ["assert 1"])]) == []


# ---------- evidence bundle ----------

def related(chunk_id: int, text: str) -> RetrievedChunk:
  return RetrievedChunk(chunk_id, f"lib/{chunk_id}.py", None, 1, 5, text, 0.1, ("vector",))


def test_bundle_ids_kinds_and_hunk_lines():
  files = [diff("app/x.py", ["a = eval(b)"]), diff("app/y.py", ["c = 1", "d = 2"])]
  bundle = build_bundle(
    "Title", "Body", files, detect_signals(files),
    {("app/x.py", 0): [(1, 3, "def f():\n  a = eval(b)")]},
    {("app/x.py", 0): [related(7, "def g(): pass")]},
  )

  assert [(item.id, item.kind) for item in bundle.items] == [
    ("S1", "signal"), ("H1", "hunk"), ("H2", "hunk"), ("F1", "function"), ("R1", "related"),
  ]
  assert bundle.get("H2").new_lines == (1, 2)
  assert bundle.get("H9") is None


def test_budget_keeps_the_most_important_items():
  files = [diff("app/x.py", ["x = 1"])]
  big_context = {("app/x.py", 0): [related(1, "y" * 4000), related(2, "short")]}

  bundle = build_bundle("T", "", files, [], {}, big_context, budget=200)

  assert [item.kind for item in bundle.items] == ["hunk", "related"]
  assert bundle.dropped == 1
  assert bundle.tokens <= 200


def test_each_hunks_best_match_comes_before_second_best():
  files = [diff("a.py", ["x"]), diff("b.py", ["y"])]
  matches = {("a.py", 0): [related(1, "a1"), related(2, "a2")], ("b.py", 0): [related(3, "b1"), related(1, "dup")]}

  bundle = build_bundle("T", "", files, [], {}, matches)

  assert [item.path for item in bundle.items if item.kind == "related"] == ["lib/1.py", "lib/3.py", "lib/2.py"]


def test_long_description_is_cut():
  bundle = build_bundle("T", "word " * 10_000, [], [], {}, {})

  assert estimate_tokens(bundle.description) <= 401
