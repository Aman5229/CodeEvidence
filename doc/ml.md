# ML risk model

The rule score ([risk.md](risk.md)) uses hand-picked weights. This model learns the weights
from past PRs, is compared honestly against the rule score, and is served next to it.

**Status:** the pipeline is built and tested on synthetic data. The numbers come from
real data: after the backfill, run the three commands below; they write
[ml-results.md](ml-results.md). Nothing in this document is a measured result.

```bash
python -m scripts.backfill_pull_requests <20+ repos> --max-prs 250   # about 5,000 PRs
python -m scripts.export_risk_dataset          # database -> data/risk_dataset.csv
python -m scripts.train_risk_model             # CSV -> models/risk_model.joblib + doc/ml-results.md
```

Repositories that merge through GitHub's merge button (so "closed without merge" really
means rejected): `fastapi/fastapi pallets/flask psf/requests encode/httpx pydantic/pydantic
encode/starlette fastapi/sqlmodel psf/black pytest-dev/pytest celery/celery aio-libs/aiohttp
python-poetry/poetry pypa/pip scrapy/scrapy Textualize/rich marshmallow-code/marshmallow
tornadoweb/tornado httpie/cli pallets/click pallets/jinja`. **Avoid** projects that merge by
pushing commits themselves and then close the PR (for example `django/django`,
`sqlalchemy/sqlalchemy`): their merged work would be labelled rejected. Backfilling 5,000
PRs makes about 5,000 file requests; at GitHub's 5,000 requests per hour, expect the
rate-limit pause to kick in once.

## 1. What is predicted (the label)

`rejected` = 1 when a PR was **closed without being merged**, 0 when it was merged. Only
closed PRs are used, because an open PR has no outcome yet.

Why this label: it is recorded for every PR and needs no manual labelling. It is a proxy for
risk: a PR can be closed for reasons unrelated to quality (a duplicate, the author gave up, a
bot PR replaced by a newer one). Better labels ("reverted within 30 days", "followed by a
bug fix touching the same lines") need more data work, and are noted as future work.

## 2. Inputs, and the leakage checklist

Inputs (`app/modules/ml/features.py`): log lines changed, log files changed, test file
ratio, docs only, bot author, size within the repository, log of the author's earlier PRs
in the repository, the share of those that were merged, and whether the PR has a description.

Leakage means the model sees information it would not have when the PR is opened. Then it
looks good in testing and fails in use. Checklist:

| Check | How it is handled |
|---|---|
| No outcome fields as inputs | `merged_at`, `closed_at`, review results and comment counts are never inputs |
| Size within the repository uses only earlier PRs | `build_rows` compares each PR with the PRs opened **before** it. The stored risk rows are not reused, because rescoring compares each PR with all PRs, later ones included |
| Author history uses only the past | earlier PRs are those opened before this one; a merge counts only if it happened before this PR was opened |
| No random split | the split is by time: the newest 20% is the test set, so the model never trains on the future |
| Cross-validation keeps time order | `TimeSeriesSplit`: each fold trains on older PRs and validates on newer ones |
| Threshold and calibration are not fitted on the test set | both use the newest 20% of the training set |
| One feature definition for training and serving | `model_inputs()` is the only place features are computed, for both |

## 3. How it is trained (`app/modules/ml/training.py`)

1. **Split by time:** oldest 80% train, newest 20% test.
2. **Baselines:** always predict the majority class; the rule score (rules-v1); lines changed
   alone. The model must beat "bigger PRs are riskier", otherwise it adds nothing.
3. **Logistic regression:** inputs scaled, balanced class weights, regularisation strength
   `C` chosen by time-ordered cross-validation.
4. **Gradient-boosted trees** (`HistGradientBoostingClassifier`): a small grid (depth,
   learning rate, rounds, leaf size), the same cross-validation.
5. **The better one** by cross-validated PR-AUC is chosen. PR-AUC rather than ROC-AUC,
   because it focuses on the PRs that matter (the rejected ones) when they are a minority.
6. **Calibration:** sigmoid (Platt) scaling on the newest part of the training set, so
   "0.7" means "about 70% of such PRs were rejected". The reliability table in the results
   shows whether that holds on the test set.
7. **Threshold:** the cut-off with the lowest cost, where missing a rejected PR costs 3 and
   a false alarm costs 1. This is a product decision: a reviewer would rather check one PR
   too many than miss a bad one. Change `FALSE_NEGATIVE_COST` to move it.
8. **Error analysis:** permutation importance (how much PR-AUC drops when a feature is
   shuffled), logistic regression coefficients, metrics for bots vs people separately, and
   the 10 most confident mistakes, listed by PR id to read on GitHub.

## 4. Model card

| | |
|---|---|
| Model | Calibrated logistic regression or gradient-boosted trees, whichever cross-validates better |
| Predicts | Chance that a PR is closed without being merged |
| Trained on | Closed PRs from public repositories backfilled from GitHub (list in the export output) |
| Intended use | Rank PRs for review attention, next to the rule score and its reasons |
| Not for | Judging people. Low author history raises the score, so new contributors get flagged more often: this is a pattern in the data, not a statement about their work |
| File | `models/risk_model.joblib`: the estimator, threshold, feature list, training date, dataset SHA-256, scikit-learn version, test metrics, and the training distribution of each feature |
| Reproduce | `python -m scripts.train_risk_model data/risk_dataset.csv` (fixed seeds, the CSV's SHA-256 is recorded) |
| Known limits | The label is a proxy; the repositories are popular open-source Python projects, so other kinds of repositories may differ; the data is a few thousand PRs |

**Security note:** a `.joblib` file is a pickle, and loading a pickle can run code. The app
only loads the file at `RISK_MODEL_PATH`, which this project trains. Never load a model
file from someone else.

## 5. Serving (`app/modules/ml/serving.py`)

- The worker scores each PR with the rules **and** the model, after the file sync. The
  model's output is stored in `pull_request_risks` (`model_version`, `model_probability`,
  `model_flagged`, `model_inputs`).
- `GET /pull-requests/{id}/risk` returns the rule score and its reasons as before, plus
  `model: {version, probability, flagged}`. This is **shadow mode**: the rule score stays the
  primary answer, until the model has proven itself.
- **Fallback:** with no model file, an unreadable one, or one trained on other features,
  `model` is `null` and everything else works. The model loads once per process.
- After training a new model, restart the app and worker, then rescore:
  `python -m scripts.score_pull_requests`.

## 6. Drift (`app/modules/ml/drift.py`)

The model inputs stored for each scored PR are a prediction log. `python -m
scripts.drift_report` compares the last 30 days with the training data, feature by feature,
using the population stability index (PSI): below 0.1 stable, 0.1 to 0.25 watch, above 0.25
retrain. Run it weekly from cron (scheduled runs are not set up in this project yet).
