"""Background jobs. Each job has a job_runs row (status, attempts, errors); Celery carries its id."""

import asyncio
import logging
import random
import time
from collections.abc import Callable

from celery import Task
from celery.exceptions import Retry
from pydantic import BaseModel
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.cache import invalidate_pull_request
from app.core.logs import delivery_id_var, job_id_var, request_id_var
from app.db.models import GitHubEvent, JobRun, Learning, PullRequest, Repository, Review, ReviewFinding
from app.db.redis import redis_client
from app.db.session import SessionLocal
from app.integrations.github.client import get_github_client
from app.core.config import settings
from app.integrations.github.guard import (
  GitHubGuard,
  ServiceUnavailable,
  is_retryable,
  rate_limit_wait_seconds,
)
from app.modules.code.embeddings import get_embedder
from app.modules.code.indexing import index_repository as index_repository_code
from app.modules.ingestion.service import process_stored_event, sync_files_for_pull_request
from app.modules.job_runs import (
  create_job_run,
  fail_job_run,
  finish_job_run,
  requeue_job_run,
  start_job_run,
)
from app.modules.review.chat import (
  HELP_TEXT,
  Mention,
  answer,
  answer_marker,
  chat_bundle,
  comment_from_event,
  github_reply,
  history,
  is_own_comment,
  parse_mention,
  render_for_github,
  save_exchange,
)
from app.modules.review.feedback import finding_for_comment
from app.modules.review.learnings import (
  MAX_LEARNING_CHARS,
  MIN_LEARNING_CHARS,
  create_learning,
  distill,
  is_blanket_rule,
)
from app.modules.review.llm import BudgetExceeded, CostMeter, LLMError, LLMGuard, get_llm
from app.modules.review.publishing import dashboard_link, publishing_allowed
from app.modules.review.publishing import publish_review as publish_review_to_github
from app.modules.review.service import review_pull_request as review_pull_request_with_llm
from app.modules.risk.service import compute_risk
from app.schemas.jobs import (
  AnswerMentionPayload,
  DistillLearningPayload,
  IndexRepositoryPayload,
  JobMessage,
  ProcessEventPayload,
  PublishReviewPayload,
  ReviewPullRequestPayload,
  SyncPullRequestFilesPayload,
)
from app.worker import celery_app

logger = logging.getLogger(__name__)

# Retries: exponential backoff with full jitter, for up to MAX_RETRIES real failures.
# Pauses (GitHub or the LLM rate-limited, or a circuit open) wait without using up that budget.
RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 300
MAX_RETRIES = 5
# Waits stay well below Redis's visibility timeout (1 h): a message held longer is redelivered.
MAX_PAUSE_SECONDS = 900


def retry_delay_seconds(attempt: int) -> float:
  """Full jitter: a random wait between 0 and BASE * 2^attempt, capped at MAX."""
  return random.uniform(0, min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * 2**attempt))


def pause_seconds(error: Exception) -> float | None:
  """How long the service asked us to wait (rate limit or open circuit), if it did."""
  if isinstance(error, ServiceUnavailable):
    return error.retry_after
  if isinstance(error, LLMError):
    return error.retry_after
  return rate_limit_wait_seconds(error)


def should_retry(error: Exception) -> bool:
  return is_retryable(error) or (isinstance(error, LLMError) and error.transient)


def retry_countdown(error: Exception, failures: int) -> float:
  """How long to wait before the next try. Pauses get a little jitter so workers don't wake together."""
  pause = pause_seconds(error)
  if pause is not None:
    return min(MAX_PAUSE_SECONDS, pause) + random.uniform(0, 1)
  return retry_delay_seconds(failures)


def get_github_guard() -> GitHubGuard:
  return GitHubGuard(redis_client)


def get_llm_guard() -> LLMGuard:
  return LLMGuard(redis_client)


# ---------- the worker side ----------

def run_tracked(task: Task, message: dict, handler: Callable[[Session, JobRun], None]) -> None:
  """Run one job and record it: running, then succeeded, retrying or failed (dead letter).

  The request and delivery ids from the message are restored, so the job's log lines can be
  matched with the webhook request that queued it.
  """
  received = JobMessage.model_validate(message)
  tokens = [
    request_id_var.set(received.request_id),
    delivery_id_var.set(received.delivery_id),
    job_id_var.set(received.job_id),
  ]
  started = time.perf_counter()
  try:
    _run(task, received, handler, started)
  finally:
    for var, token in zip((request_id_var, delivery_id_var, job_id_var), tokens, strict=True):
      var.reset(token)


def _run(task: Task, received: JobMessage, handler, started: float) -> None:
  with SessionLocal() as db:
    job = start_job_run(db, received.job_id)
    logger.info("Job started", extra={"job_type": job.job_type, "attempt": job.attempts})
    try:
      handler(db, job)
    except Exception as error:
      db.rollback()
      paused = pause_seconds(error) is not None
      will_retry = paused or (should_retry(error) and received.failures < MAX_RETRIES)
      fail_job_run(job, error, will_retry=will_retry)
      db.commit()
      outcome = "paused" if paused else "retrying" if will_retry else "failed"
      log = logger.warning if will_retry else logger.error
      log("Job %s: %s", outcome, error, extra={"job_type": job.job_type, "outcome": outcome})
      if will_retry:
        failures = received.failures if paused else received.failures + 1
        try:
          task.retry(
            args=[received.model_copy(update={"failures": failures}).model_dump()],
            countdown=retry_countdown(error, received.failures),
            exc=error,
          )  # raises Retry once the retry is scheduled
        except Retry:
          raise
        except Exception as retry_error:
          if retry_error is error:
            raise  # called directly, not from the queue: Celery re-raises; nothing to schedule
          # The retry could not be scheduled (e.g. Redis down): make it a visible dead letter
          # instead of leaving it "retrying" with no message to run it.
          fail_job_run(job, retry_error, will_retry=False)
          db.commit()
          raise
      raise
    finish_job_run(job)
    db.commit()
    logger.info(
      "Job succeeded",
      extra={"job_type": job.job_type, "duration_ms": round((time.perf_counter() - started) * 1000, 1)},
    )


def _process_event(db: Session, job: JobRun) -> None:
  payload = ProcessEventPayload.model_validate(job.payload)
  repository_id, pull_request_id = process_stored_event(db, payload.event_id)
  if pull_request_id is not None:
    invalidate_pull_request(redis_client, repository_id, pull_request_id)
    enqueue_job(
      db,
      sync_pr_files,
      SyncPullRequestFilesPayload(pull_request_id=pull_request_id),
      event_id=payload.event_id,
    )
  _queue_comment_follow_up(db, payload.event_id)


def _queue_comment_follow_up(db: Session, event_id: int) -> None:
  """A new PR comment may ask CodeEvidence something (a mention), or say why one of its
  findings was wrong (a reply in its thread: a possible learning)."""
  event = db.get(GitHubEvent, event_id)
  comment = comment_from_event(db, event.event_type, event.payload)
  if comment is None or not comment.trusted or is_own_comment(comment.body):
    return
  pull_request = db.get(PullRequest, comment.pull_request_id)
  if not publishing_allowed(db.get(Repository, pull_request.repository_id).full_name):
    return  # CodeEvidence talks on GitHub only where it may write
  if parse_mention(comment.body) is not None:
    mention = AnswerMentionPayload(
      pull_request_id=comment.pull_request_id, comment_id=comment.comment_id, kind=comment.kind,
      body=comment.body, author=comment.author, in_reply_to_id=comment.in_reply_to_id,
    )
    enqueue_job(db, answer_mention, mention, event_id=event_id)
  elif comment.kind == "review" and comment.body.strip():
    finding = finding_for_comment(db, comment.in_reply_to_id)
    if finding is not None:
      reason = DistillLearningPayload(finding_id=finding.id, reason=comment.body[:2000], source="github")
      enqueue_job(db, distill_learning, reason, event_id=event_id)


def _sync_pr_files(db: Session, job: JobRun) -> None:
  payload = SyncPullRequestFilesPayload.model_validate(job.payload)
  guard = get_github_guard()
  guard.before_call()  # raises ServiceUnavailable while rate-limited or the circuit is open
  try:
    repository_id = asyncio.run(
      sync_files_for_pull_request(db, get_github_client(), payload.pull_request_id)
    )
  except Exception as error:
    guard.record_failure(error)
    raise
  guard.record_success()
  compute_risk(db, payload.pull_request_id)  # needs the files, so it runs after the sync
  invalidate_pull_request(redis_client, repository_id, payload.pull_request_id)
  if settings.review_on_sync:
    enqueue_job(
      db, review_pull_request, ReviewPullRequestPayload(pull_request_id=payload.pull_request_id), event_id=job.event_id
    )


def _guarded(guard: GitHubGuard, call):
  """Run `call` through a guard: refuse while paused, record the outcome."""
  guard.before_call()  # raises ServiceUnavailable while rate-limited or the circuit is open
  try:
    result = call()
  except Exception as error:
    guard.record_failure(error)
    raise
  guard.record_success()
  return result


def _index_repository(db: Session, job: JobRun) -> None:
  payload = IndexRepositoryPayload.model_validate(job.payload)
  result = _guarded(
    get_github_guard(),
    lambda: asyncio.run(index_repository_code(db, get_github_client(), get_embedder(), payload.repository_id)),
  )
  logger.info("Repository indexed", extra={"repository_id": payload.repository_id, **vars(result)})


def _with_llm(call):
  """Run `call` (which uses the LLM) through the LLM guard: refuse while paused, record the outcome."""
  guard = get_llm_guard()
  guard.before_call()
  try:
    result = call()
  except LLMError as error:
    guard.record_failure(error)
    raise
  guard.record_success()
  return result


def _review_pull_request(db: Session, job: JobRun) -> None:
  payload = ReviewPullRequestPayload.model_validate(job.payload)
  github_guard, llm_guard = get_github_guard(), get_llm_guard()
  llm = get_llm()  # first: a missing key or wrong provider fails before any slow work
  llm_guard.before_call()
  try:
    review = _guarded(
      github_guard,
      lambda: asyncio.run(
        review_pull_request_with_llm(
          db, get_github_client(), get_embedder(), llm, payload.pull_request_id,
          budget_usd=settings.review_budget_usd, mode=payload.mode,
        )
      ),
    )
  except LLMError as error:
    llm_guard.record_failure(error)  # the GitHub guard ignores LLM errors, and the reverse
    raise
  llm_guard.record_success()
  logger.info(
    "Pull request reviewed",
    extra={"review_id": review.id, "status": review.status, "cost_usd": review.cost_usd, "cached": review.cached},
  )
  if review.status == "completed" and settings.publish_repositories:
    enqueue_job(db, publish_review, PublishReviewPayload(review_id=review.id), event_id=job.event_id)


def _publish_review(db: Session, job: JobRun) -> None:
  payload = PublishReviewPayload.model_validate(job.payload)
  _guarded(get_github_guard(), lambda: asyncio.run(publish_review_to_github(db, get_github_client(), payload.review_id)))


def _distill_learning(db: Session, job: JobRun) -> None:
  payload = DistillLearningPayload.model_validate(job.payload)
  finding = db.get(ReviewFinding, payload.finding_id)
  if finding is None:
    raise ValueError(f"Finding {payload.finding_id} does not exist")
  if db.scalar(select(exists().where(Learning.source_finding_id == finding.id, Learning.source == payload.source))):
    logger.info("This finding already gave a learning", extra={"finding_id": finding.id})
    return
  llm = get_llm()
  distilled = _with_llm(
    lambda: distill(
      CostMeter(llm, settings.chat_budget_usd),
      path=finding.path, claim=finding.claim, quote=finding.quote, reason=payload.reason,
    )
  )
  if distilled.rule is None:
    logger.info("No rule in this feedback", extra={"finding_id": finding.id})
    return
  repository_id = db.scalar(
    select(PullRequest.repository_id).join(Review, Review.pull_request_id == PullRequest.id).where(Review.id == finding.review_id)
  )
  learning = create_learning(
    db, get_embedder(), repository_id=repository_id, text=distilled.rule, path_glob=distilled.path_glob,
    source=payload.source, enabled=payload.source == "dashboard",  # from GitHub: approved in the dashboard first
    source_finding_id=finding.id,
  )
  db.commit()
  logger.info("Learning saved", extra={"learning_id": learning.id, "enabled": learning.enabled})


def _answer_mention(db: Session, job: JobRun) -> None:
  payload = AnswerMentionPayload.model_validate(job.payload)
  mention = parse_mention(payload.body)
  pull_request = db.get(PullRequest, payload.pull_request_id)
  if mention is None or pull_request is None:
    return
  repository = db.get(Repository, pull_request.repository_id)
  if not publishing_allowed(repository.full_name):
    logger.info("Not answering on %s: not in PUBLISH_REPOSITORIES", repository.full_name)
    return
  github, guard = get_github_client(), get_github_guard()
  if _guarded(guard, lambda: asyncio.run(_answered_already(github, repository.full_name, pull_request.number, payload))):
    return  # a retried job: the reply is already there
  text = _carry_out(db, job, pull_request, mention, payload)
  body = github_reply(text, dashboard_link(pull_request.id), payload.comment_id)
  _guarded(guard, lambda: asyncio.run(_post_reply(github, repository.full_name, pull_request.number, payload, body)))
  db.commit()


async def _answered_already(github, repo_full_name: str, number: int, payload: AnswerMentionPayload) -> bool:
  if payload.kind == "issue":
    comments = await github.list_issue_comments(repo_full_name, number)
  else:
    comments = await github.list_review_comments(repo_full_name, number)
  marker = answer_marker(payload.comment_id)
  return any(marker in (comment.get("body") or "") for comment in comments)


async def _post_reply(github, repo_full_name: str, number: int, payload: AnswerMentionPayload, body: str) -> None:
  if payload.kind == "issue":
    await github.create_issue_comment(repo_full_name, number, body)
  else:  # replies go to the thread's first comment: GitHub has no replies to replies
    await github.reply_to_review_comment(repo_full_name, number, payload.in_reply_to_id or payload.comment_id, body)


def _carry_out(db: Session, job: JobRun, pull_request: PullRequest, mention: Mention, payload: AnswerMentionPayload) -> str:
  """Do what the mention asks; returns the text of the reply."""
  if mention.command == "help":
    return HELP_TEXT
  if mention.command in ("review", "full_review"):
    mode = "full" if mention.command == "full_review" else "auto"
    review = ReviewPullRequestPayload(pull_request_id=pull_request.id, mode=mode)
    enqueue_job(db, review_pull_request, review, event_id=job.event_id)
    started = "Starting a full review of this pull request." if mode == "full" else (
      "Starting a review of the changes since the last review."
    )
    return f"{started} The walkthrough comment will be updated when it is done."
  if mention.command == "remember":
    return _remember(db, pull_request, mention.text, payload)
  return _ask(db, pull_request, mention.text, payload)


def _remember(db: Session, pull_request: PullRequest, text: str, payload: AnswerMentionPayload) -> str:
  rule = " ".join(text.split())
  if len(rule) < MIN_LEARNING_CHARS:
    return "Write the rule after `remember`, for example: `@codeevidence remember request bodies in src/api are validated by middleware`."
  if len(rule) > MAX_LEARNING_CHARS:
    return f"Not saved: keep the rule under {MAX_LEARNING_CHARS} characters."
  if is_blanket_rule(rule):
    return "Not saved: a rule must not turn off a whole category of findings."
  finding = finding_for_comment(db, payload.in_reply_to_id) if payload.kind == "review" else None
  create_learning(
    db, get_embedder(), repository_id=pull_request.repository_id, text=rule, path_glob=None, source="github",
    enabled=False, source_finding_id=finding.id if finding else None,
  )
  return "Saved as a proposed learning. It applies to future reviews of this repository once someone approves it in the dashboard."


def _ask(db: Session, pull_request: PullRequest, question: str, payload: AnswerMentionPayload) -> str:
  bundle = chat_bundle(db, get_embedder(), pull_request, question, settings.chat_token_budget)
  earlier = history(db, pull_request.id)
  llm = get_llm()
  try:
    result = _with_llm(lambda: answer(CostMeter(llm, settings.chat_budget_usd), bundle, earlier, question))
  except BudgetExceeded:
    return "Sorry, answering this would go over the budget for one answer. Try a narrower question."
  save_exchange(
    db, pull_request.id, question, result, bundle, source="github", model=llm.model,
    github_user=payload.author, github_comment_id=payload.comment_id,
  )
  return render_for_github(result.text, bundle)


@celery_app.task
def ping(seconds: float = 0) -> str:
  """Proves a job travels from the queue to a worker. `seconds` makes it slow, to test shutdown."""
  time.sleep(seconds)
  return "pong"


# max_retries=None: Celery must not cap retries itself. Its counter also counts pauses, so a
# job that waited out an open circuit a few times would be dropped. run_tracked keeps the budget.
@celery_app.task(bind=True, max_retries=None)
def process_event(self, message: dict) -> None:
  """Stored webhook event -> repository and PR rows; then queue the file sync."""
  run_tracked(self, message, _process_event)


@celery_app.task(bind=True, max_retries=None)
def sync_pr_files(self, message: dict) -> None:
  """Fetch a PR's changed files from GitHub (the slow, failure-prone part)."""
  run_tracked(self, message, _sync_pr_files)


@celery_app.task(bind=True, max_retries=None)
def index_repository(self, message: dict) -> None:
  """Chunk and embed a repository's code for retrieval (only files changed since last time)."""
  run_tracked(self, message, _index_repository)


@celery_app.task(bind=True, max_retries=None)
def review_pull_request(self, message: dict) -> None:
  """AI review of a PR: evidence, LLM findings, verification, ranking."""
  run_tracked(self, message, _review_pull_request)


@celery_app.task(bind=True, max_retries=None)
def publish_review(self, message: dict) -> None:
  """Post a review's findings as inline comments on GitHub (allowed repositories only)."""
  run_tracked(self, message, _publish_review)


@celery_app.task(bind=True, max_retries=None)
def distill_learning(self, message: dict) -> None:
  """Turn a reviewer's reason for rejecting a finding into a learning for future reviews."""
  run_tracked(self, message, _distill_learning)


@celery_app.task(bind=True, max_retries=None)
def answer_mention(self, message: dict) -> None:
  """Answer a PR comment that mentions @codeevidence: a command or a question."""
  run_tracked(self, message, _answer_mention)


# ---------- the producer side ----------

JOB_TASKS = {
  task.name.rsplit(".", 1)[-1]: task
  for task in (
    process_event, sync_pr_files, index_repository, review_pull_request, publish_review, distill_learning,
    answer_mention,
  )
}


def new_message(job_id: int) -> JobMessage:
  """A job message that carries the current request and delivery ids to the worker's logs."""
  return JobMessage(job_id=job_id, request_id=request_id_var.get(), delivery_id=delivery_id_var.get())


def dispatch(task: Task, message: JobMessage) -> None:
  """The only place that talks to the broker. Tests replace it with a fake."""
  task.delay(message.model_dump())


def enqueue_job(db: Session, task: Task, payload: BaseModel, *, event_id: int | None) -> JobRun:
  """Record the job, commit, then queue it. If queueing fails, the job is marked failed."""
  job_type = task.name.rsplit(".", 1)[-1]
  job = create_job_run(db, job_type=job_type, payload=payload.model_dump(), event_id=event_id)
  db.commit()  # before queueing, so the worker can already see the row
  try:
    dispatch(task, new_message(job.id))
  except Exception as error:
    fail_job_run(job, error, will_retry=False)
    db.commit()
    raise
  return job


def retry_failed_job(db: Session, job: JobRun) -> None:
  """Queue a dead letter again. If queueing fails, it stays failed."""
  requeue_job_run(job)
  db.commit()
  try:
    dispatch(JOB_TASKS[job.job_type], new_message(job.id))
  except Exception as error:
    fail_job_run(job, error, will_retry=False)
    db.commit()
    raise


def enqueue_process_event(db: Session, event_id: int) -> JobRun:
  return enqueue_job(db, process_event, ProcessEventPayload(event_id=event_id), event_id=event_id)
