# Review quality: publishing, feedback and evaluation

**Status:** the publishing, feedback and evaluation code is built and tested. The quality
numbers below need real reviews and hand labels. The CI gate currently runs on three
**hand-written** cases that exercise the pipeline (marked as synthetic in their files);
they are to be replaced by recorded real reviews. No number here is a measured result yet.

## 1. Posting to GitHub (`app/modules/review/publishing.py`)

**Auth decision:** a fine-grained personal access token, limited to one sandbox repository
with "Pull requests: read and write". A GitHub App (installation tokens, per-repository
install, its own bot identity) is the right choice for other people's repositories, and the
next step if this runs beyond a sandbox. Logged in [decisions.md](decisions.md).

- One PR review per run, `event: COMMENT` (never approves or blocks), with one inline
  comment per ranked finding on the new-file line (`side: RIGHT`).
- **Only repositories in `PUBLISH_REPOSITORIES` are written to.** Everything else is skipped.
- A review made for an older commit is not posted.

**Idempotent publishing.** Each comment ends with a hidden marker,
`<!-- codeevidence:<finding key> -->`. The key is a hash of path, category and quoted code,
so the same problem on the same code gets the same key even if the model words it
differently. Before posting, the PR's comments are read and known keys are skipped. So a
retried job, a crash after posting, a redelivered webhook, or a review of the next commit
that finds the same problem never posts a duplicate. When new commits change the commented
lines, GitHub marks the old comment as outdated.

## 2. Feedback (`feedback.py`, table `finding_feedback`)

| Source | How it arrives | Verdict |
|---|---|---|
| 👍 ❤️ 🎉 / 👎 😕 on our comment | polled: `python -m scripts.collect_feedback` (GitHub has no webhook for reactions) | useful / not useful |
| A reply to our comment | webhook `pull_request_review_comment` | none, the text is stored |
| Thread resolved | webhook `pull_request_review_thread` | none: "fixed" and "dismissed" look the same |
| Dashboard button | `POST /findings/{id}/feedback` | useful / not useful |

Every GitHub item stores the id it came from, so collecting twice records it once. Enable the
two webhook events in the GitHub webhook settings.

## 3. Gold set and labelling rules

```bash
python -m scripts.evaluate_reviews export --limit 60   # eval/findings_gold.jsonl
# set "label" on each line
python -m scripts.evaluate_reviews report
```

Labels:
- **useful:** correct, about this PR, and worth a reviewer's time.
- **wrong:** about real code, but the claim is mistaken, trivial or not worth a comment.
- **not_grounded:** about code or behaviour the PR does not contain (a hallucination).

Rules: open the PR on GitHub and read the code before labelling; judge the claim, not the
wording; when unsure between useful and wrong, choose wrong. **Bias:** the person who built
the reviewer also labels its output, and may be generous. Mitigations: fixed rules written
before labelling, labelling in random order, and re-labelling 10 findings a week later to
check consistency.

## 4. Metrics (`app/modules/review/evaluation.py`)

| Metric | Meaning |
|---|---|
| Precision | useful / shown findings |
| Grounded rate | shown findings not labelled not_grounded |
| Hallucination rate after verification | not_grounded / shown |
| Dropped by the verifier | proposed findings that failed verification |
| Latency p50 / p95 | per review |
| Cost per review | mean, from stored token counts |

Every rate has a **95% Wilson interval**. With 50 labels a measured 70% means "somewhere
between about 56% and 81%": small sets cannot separate close numbers, and the report says so.

## 5. Evaluation in CI (record and replay)

`python -m scripts.record_eval_case <pull_request_id> --name <name>` runs the real model once
and saves the evidence and the model's raw answers to `eval/cases/<name>.json`; you then label
each proposed finding. In CI, `tests/unit/test_review_evaluation.py` replays every case
through the production pipeline with a fake LLM that returns the recorded answers: no API
calls, no cost, fully deterministic. The gate fails CI when a metric drops below
`eval/thresholds.json`:

| Gate | Minimum |
|---|---|
| `shown_precision` | 60% |
| `shown_grounded` | 95% |
| `hallucinations_caught` (not_grounded findings the verifier dropped) | 90% |

**Proof the gate works:** a test breaks verification on purpose (keeps every finding) and
asserts that the gate fails. Replay tests the code (verification, ranking, parsing), not the
model: a new model or prompt needs new recordings.

## 6. Quality report

| Metric | Value |
|---|---|
| Labelled findings | *pending* |
| Precision | *pending* |
| Grounded rate | *pending* |
| Dropped by the verifier | *pending* |
| Latency p50 / p95 | *pending* |
| Cost per review | *pending* |

What these numbers will not prove: the reviewer is as good as a person (no comparison was
made); it works on other repositories or languages (the set is small, Python-heavy
open-source code); or that every useful finding was found (recall is not measured: nobody
listed all the problems in each PR). Not built: an LLM-as-judge for suggestion quality
(stretch task).
