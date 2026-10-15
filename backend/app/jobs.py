"""Sync job queue: enqueueing, claiming, and running SyncJobs.

The SyncJob table is the queue (decision 004). One active job per Item is
enforced by a partial unique constraint (decision 008). Retries re-queue the
same job; each execution gets a SyncAttempt row (decision 011).
"""
import json
import random
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from app.models import PlaidItem, SyncJob, SyncAttempt

from urllib3.exceptions import MaxRetryError, NewConnectionError, ProtocolError, TimeoutError

import plaid


# --- Retry configuration (decisions 010 and 013) ---------------------------

BASE_DELAY_SECONDS = 15
BACKOFF_MULTIPLIER = 2
MAX_DELAY_SECONDS = 10 * 60
MAX_ATTEMPTS = 7
JITTER_FRACTION = 0.20  # +/-20%

RETRYABLE_PLAID_ERROR_CODES = {
    'RATE_LIMIT_EXCEEDED',
    'INSTITUTION_DOWN',
    'INSTITUTION_NOT_RESPONDING',
    'INTERNAL_SERVER_ERROR',
    'TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION',
}

# Network-level failures raised by urllib3 under the Plaid client. Verified by
# triggering them against unreachable hosts: connection failures arrive wrapped
# in MaxRetryError; read timeouts and dropped connections on POST arrive unwrapped.
#   TimeoutError       -> parent of ConnectTimeoutError and ReadTimeoutError
#   NewConnectionError -> connection refused / DNS failure
#   ProtocolError      -> connection dropped mid-response
TRANSIENT_NETWORK_ERRORS = (TimeoutError, NewConnectionError, ProtocolError)

# Decision 020: each Item gets a reconcile job at most once per interval.
RECONCILE_INTERVAL = timedelta(hours=24)


def _is_transient_network_error(exc):
    """True if exc is a network failure that a retry could plausibly fix.

    MaxRetryError means urllib3 already retried and gave up; its .reason holds the
    underlying failure. Only retry if that underlying cause is transient: a
    MaxRetryError caused by an SSL or proxy error would fail the same way again.
    """
    if isinstance(exc, MaxRetryError):
        return isinstance(exc.reason, TRANSIENT_NETWORK_ERRORS)
    return isinstance(exc, TRANSIENT_NETWORK_ERRORS)


def enqueue_sync(plaid_item):
    """Queue a sync for this Item, or return its existing active job."""
    return enqueue_job(plaid_item, kind=SyncJob.Kind.SYNC)


def enqueue_job(plaid_item, kind):
    """Queue a job of this kind, or return the Item's existing active job (of any kind).

    The nested atomic() creates a savepoint. If the INSERT violates the
    one-active-job constraint, only the savepoint rolls back, so a caller's
    surrounding transaction (e.g. in exchange_public_token) stays usable.
    """
    try:
        with transaction.atomic():
            return SyncJob.objects.create(plaid_item=plaid_item, kind=kind)
    except IntegrityError:
        return SyncJob.objects.get(
            plaid_item=plaid_item,
            status__in=SyncJob.ACTIVE_STATUSES,
        )


def enqueue_due_reconciles(now=None):
    """Queue a reconcile for every Item without one created in the last RECONCILE_INTERVAL.

    Called periodically by the worker (decision 020). If an Item has a sync
    active, enqueue_job returns that job instead and nothing is queued; the
    next check tries again. Returns the number of reconcile jobs queued.
    """
    now = now or timezone.now()
    recently_reconciled = SyncJob.objects.filter(
        kind=SyncJob.Kind.RECONCILE,
        created_at__gte=now - RECONCILE_INTERVAL,
    ).values('plaid_item_id')

    queued = 0
    for item in PlaidItem.objects.exclude(id__in=recently_reconciled):
        job = enqueue_job(item, kind=SyncJob.Kind.RECONCILE)
        if job.kind == SyncJob.Kind.RECONCILE:
            queued += 1
    return queued


def compute_backoff(attempt_number, rng=random.random):
    """Seconds to wait after attempt `attempt_number` fails, before the next one.

    - attempt 1 -> ~BASE_DELAY_SECONDS, doubling each attempt (BACKOFF_MULTIPLIER).
    - Never more than MAX_DELAY_SECONDS before jitter is applied.
    - Jitter: scale the delay by a random factor in [1 - JITTER_FRACTION, 1 + JITTER_FRACTION].
    - `rng` returns a float in [0, 1). Tests pass a fixed function to make the
      result deterministic, e.g. rng=lambda: 0.5 means "no jitter".
    """
    delay = BASE_DELAY_SECONDS * (BACKOFF_MULTIPLIER ** (attempt_number - 1))
    delay = min(delay, MAX_DELAY_SECONDS)
    jitter_factor = 1 + JITTER_FRACTION * (2 * rng() - 1)
    return delay * jitter_factor


def is_retryable(exc):
    """True only for errors on the allowlist (decision 010).

    - plaid.ApiException: retryable iff its error_code is in RETRYABLE_PLAID_ERROR_CODES.
    - Transient network failures (see _is_transient_network_error): retryable.
    - Everything else: not retryable.
    """
    if isinstance(exc, plaid.ApiException):
        error_code, _ = _parse_plaid_error(exc)
        return error_code in RETRYABLE_PLAID_ERROR_CODES
    return _is_transient_network_error(exc)


def claim_next_job():
    """Atomically claim the oldest due job and open an attempt for it.

    - Two workers calling this at the same time never get the same job
      (SELECT ... FOR UPDATE SKIP LOCKED).
    - "Due" means queued with no run_after, or a run_after that has passed. The
      filter is in the query, so a not-yet-due job can't block due jobs behind it.
    - In the same transaction: the job becomes in_progress with started_at set to
      this attempt's start, and a SyncAttempt row is created for this attempt.
    - Returns the SyncJob, or None when nothing is due.
    """
    now = timezone.now()
    with transaction.atomic():
        job = (
            SyncJob.objects
            .filter(status=SyncJob.Status.QUEUED)
            .filter(Q(run_after__isnull=True) | Q(run_after__lte=now))
            .order_by('created_at', 'id')
            .select_for_update(skip_locked=True)
            .first()
        )
        if job is None:
            return None

        job.status = SyncJob.Status.IN_PROGRESS
        job.started_at = now
        # Counts describe the latest attempt. A retry replays pages, so carrying
        # counts over from a failed attempt would double-count them.
        job.added_count = job.modified_count = job.removed_count = 0
        job.save(update_fields=[
            'status', 'started_at',
            'added_count', 'modified_count', 'removed_count',
        ])

        SyncAttempt.objects.create(
            job=job,
            attempt_number=job.attempt_number,
            started_at=now,
        )
    return job


def run_job(job):
    """Run the job's current attempt and record the outcome on the job and attempt.

    Three outcomes (decision 011):
    - Success: attempt completed; job completed with counts.
    - Retryable failure with attempts left: attempt retry_scheduled; job back to
      queued with attempt_number + 1 and run_after = now + backoff.
    - Otherwise: attempt failed; job failed with the final error.

    Never re-raises, so one bad job can't kill the worker loop.
    """
    # claim_next_job creates this row in the same transaction that claims the job.
    attempt = job.attempts.get(attempt_number=job.attempt_number)
    try:
        # Lazy imports: app.views imports app.jobs, so importing it at module level would be circular.
        if job.kind == SyncJob.Kind.RECONCILE:
            from app.reconcile import reconcile_item
            reconcile_item(job.plaid_item, job, attempt)
        else:
            from app.views import sync_item
            sync_item(job.plaid_item, job, attempt)
        _record_success(job, attempt)
    except Exception as e:
        error_code, error_message = _describe_error(e)

        # Retry only allowlisted errors, and only if attempts remain (decisions 010, 013).
        if is_retryable(e) and job.attempt_number < MAX_ATTEMPTS:
            delay = compute_backoff(job.attempt_number)
            _schedule_retry(job, attempt, error_code, error_message, delay)
        else:
            _record_failure(job, attempt, error_code, error_message)


# --- Outcome recording: job and attempt are always updated together ---------

def _record_success(job, attempt):
    now = timezone.now()
    with transaction.atomic():
        attempt.outcome = SyncAttempt.Outcome.COMPLETED
        attempt.finished_at = now
        attempt.save(update_fields=['outcome', 'finished_at'])

        job.status = SyncJob.Status.COMPLETED
        job.completed_at = now
        job.save(update_fields=[
            'status', 'completed_at',
            'added_count', 'modified_count', 'removed_count',
        ])


def _schedule_retry(job, attempt, error_code, error_message, delay_seconds):
    """Close this attempt as retry_scheduled and put the job back in the queue.

    The job stays active (queued), so the one-active-job constraint still holds
    while it waits. The next attempt row is created by claim_next_job.
    """
    now = timezone.now()
    with transaction.atomic():
        attempt.outcome = SyncAttempt.Outcome.RETRY_SCHEDULED
        attempt.error_code = error_code
        attempt.error_message = error_message
        attempt.finished_at = now
        attempt.save(update_fields=['outcome', 'error_code', 'error_message', 'finished_at'])

        job.status = SyncJob.Status.QUEUED
        job.attempt_number += 1
        job.run_after = now + timedelta(seconds=delay_seconds)
        job.save(update_fields=[
            'status', 'attempt_number', 'run_after',
            'added_count', 'modified_count', 'removed_count',
        ])


def _record_failure(job, attempt, error_code, error_message):
    """Close this attempt as failed and fail the job permanently."""
    now = timezone.now()
    with transaction.atomic():
        attempt.outcome = SyncAttempt.Outcome.FAILED
        attempt.error_code = error_code
        attempt.error_message = error_message
        attempt.finished_at = now
        attempt.save(update_fields=['outcome', 'error_code', 'error_message', 'finished_at'])

        job.status = SyncJob.Status.FAILED
        job.error_code = error_code
        job.error_message = error_message
        job.completed_at = now
        # Counts are saved on failure too (decision 006): pages committed before the failure count.
        job.save(update_fields=[
            'status', 'error_code', 'error_message', 'completed_at',
            'added_count', 'modified_count', 'removed_count',
        ])


# --- Error description: must never raise (runs inside exception handlers) ---

def _describe_error(e):
    """Return (error_code, error_message) for any exception. Never raises."""
    if isinstance(e, plaid.ApiException):
        return _parse_plaid_error(e)
    return None, str(e)


def _parse_plaid_error(e):
    """Return (error_code, error_message) from a plaid.ApiException. Never raises.

    A body that is missing, not JSON, or not a JSON object falls back to (None, str(e)).
    """
    try:
        body = json.loads(e.body)
    except (TypeError, ValueError):
        body = None
    if not isinstance(body, dict):
        return None, str(e)
    return body.get('error_code'), body.get('error_message') or str(e)
