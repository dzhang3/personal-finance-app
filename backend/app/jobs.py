"""Sync job queue: enqueueing, claiming, and running SyncJobs.

The SyncJob table is the queue (decision 004). One active job per Item is
enforced by a partial unique constraint (decision 008). Retries re-queue the
same job; each execution gets a SyncAttempt row (decision 011).
"""
import json
import logging
import random
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from app.logging_utils import job_context, log_event
from app.models import PlaidItem, SyncJob, SyncAttempt

from urllib3.exceptions import MaxRetryError, NewConnectionError, ProtocolError, TimeoutError

import plaid

logger = logging.getLogger(__name__)


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

# Decisions 020 and 026: each Item gets a job of each kind at most once per interval.
RECONCILE_INTERVAL = timedelta(hours=24)
SYNC_INTERVAL = timedelta(hours=6)

# Decision 030: how long a claim lasts without renewal. Renewals happen at least
# once per page, and a page takes about a second, so this only expires when the
# worker has actually stopped.
LEASE_DURATION = timedelta(seconds=60)


class LeaseLost(Exception):
    """This worker no longer owns the job: its lease expired and another worker
    claimed it (a new attempt), or the job is no longer in_progress. The worker
    must stop and write nothing more for this job."""


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
    """Queue a job of this kind, or return the Item's existing active job (of any kind)."""
    job, _ = _create_job(plaid_item, kind)
    return job


def _create_job(plaid_item, kind):
    """Returns (job, created). created is False when an active job already existed.

    The nested atomic() creates a savepoint. If the INSERT violates the
    one-active-job constraint, only the savepoint rolls back, so a caller's
    surrounding transaction (e.g. in exchange_public_token) stays usable.
    """
    try:
        with transaction.atomic():
            job = SyncJob.objects.create(plaid_item=plaid_item, kind=kind)
    except IntegrityError:
        existing = SyncJob.objects.get(
            plaid_item=plaid_item,
            status__in=SyncJob.ACTIVE_STATUSES,
        )
        log_event(logger, "job_already_active", level=logging.DEBUG,
                  item_id=plaid_item.id, requested_kind=kind, job_id=existing.id, kind=existing.kind)
        return existing, False
    log_event(logger, "job_enqueued", job_id=job.id, item_id=plaid_item.id, kind=kind)
    return job, True


def enqueue_due_reconciles(now=None):
    """Queue a reconcile for every Item without one in the last RECONCILE_INTERVAL (decision 020)."""
    return _enqueue_due(SyncJob.Kind.RECONCILE, RECONCILE_INTERVAL, now)


def enqueue_due_syncs(now=None):
    """Queue a sync for every Item without one in the last SYNC_INTERVAL (decision 026)."""
    return _enqueue_due(SyncJob.Kind.SYNC, SYNC_INTERVAL, now)


def _enqueue_due(kind, interval, now=None):
    """Queue a job of `kind` for every Item with none created within `interval`.

    Called periodically by the worker. Any job of this kind counts, including a
    manual sync or a failed one, so a failure doesn't trigger a rapid re-queue
    loop (retries already cover transient errors). If an Item has another job
    active, nothing is queued; the next check tries again. Returns the number queued.
    """
    now = now or timezone.now()
    recent = SyncJob.objects.filter(
        kind=kind,
        created_at__gte=now - interval,
    ).values('plaid_item_id')

    queued = 0
    for item in PlaidItem.objects.exclude(id__in=recent):
        _, created = _create_job(item, kind)
        queued += created
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
            .filter(_claimable(now))
            .order_by('created_at', 'id')
            .select_for_update(skip_locked=True)
            .first()
        )
        if job is None:
            return None

        if job.status == SyncJob.Status.IN_PROGRESS:
            # Reclaiming an abandoned job (decision 030): close the dead attempt
            # and start a new one. The new attempt_number is the fencing token
            # that makes any late writes from the old worker fail.
            SyncAttempt.objects.filter(
                job=job, attempt_number=job.attempt_number, outcome__isnull=True,
            ).update(outcome=SyncAttempt.Outcome.LEASE_EXPIRED, finished_at=now)
            log_event(logger, "lease_expired_reclaimed", level=logging.WARNING,
                      job_id=job.id, item_id=job.plaid_item_id, kind=job.kind,
                      abandoned_attempt=job.attempt_number, lease_expired_at=job.lease_expires_at)
            job.attempt_number += 1
            if job.attempt_number > MAX_ATTEMPTS:
                # A job that keeps killing its worker (crash loop) must not be reclaimed forever.
                job.status = SyncJob.Status.FAILED
                job.error_code = 'LEASE_EXPIRED_MAX_ATTEMPTS'
                job.error_message = f'Abandoned {MAX_ATTEMPTS} times'
                job.completed_at = now
                job.lease_expires_at = None
                job.save(update_fields=['status', 'attempt_number', 'error_code',
                                        'error_message', 'completed_at', 'lease_expires_at'])
                log_event(logger, "job_failed", level=logging.ERROR, job_id=job.id,
                          error_code=job.error_code)
                return None

        job.status = SyncJob.Status.IN_PROGRESS
        job.started_at = now
        job.lease_expires_at = now + LEASE_DURATION
        # Counts describe the latest attempt. A retry replays pages, so carrying
        # counts over from a failed attempt would double-count them.
        job.added_count = job.modified_count = job.removed_count = 0
        job.save(update_fields=[
            'status', 'started_at', 'attempt_number', 'lease_expires_at',
            'added_count', 'modified_count', 'removed_count',
        ])

        SyncAttempt.objects.create(
            job=job,
            attempt_number=job.attempt_number,
            started_at=now,
        )
    return job


# --- Leases (decision 030): Daniel writes these two -------------------------

def _claimable(now):
    """A Q() matching jobs a worker may claim right now:

      - queued and due (run_after is null or has passed), as before, OR
      - in_progress with a lease that has expired (its worker stopped renewing).

    Keep it a filter: claim_next_job's ordering and SKIP LOCKED stay unchanged.
    """
    return Q(
        Q(status=SyncJob.Status.QUEUED) &
        (Q(run_after__isnull=True) | Q(run_after__lte=now))
    ) | Q(
        Q(status=SyncJob.Status.IN_PROGRESS) &
        (Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now))
    )


def renew_lease(job):
    """Extend this worker's lease to now + LEASE_DURATION, or raise LeaseLost.

    The job is still ours only if, in the database right now, it is in_progress
    AND its attempt_number equals job.attempt_number (the fencing token: a
    reclaim increments it).

    Must be ONE conditional UPDATE, not a read followed by a save: the check and
    the write have to be atomic, or another worker can reclaim the job between
    them. Called inside transaction.atomic() before writes that matter (cursor
    save, outcome recording); the UPDATE's row lock then holds until commit,
    and claim_next_job's SKIP LOCKED can't take the job in the meantime.
    """
    now = timezone.now()
    updated = SyncJob.objects.filter(
        pk=job.pk,
        status=SyncJob.Status.IN_PROGRESS,
        attempt_number=job.attempt_number,
    ).update(lease_expires_at=now + LEASE_DURATION)
    if updated == 0:
        raise LeaseLost()


def run_job(job):
    """Run the job's current attempt and record the outcome on the job and attempt.

    Three outcomes (decision 011):
    - Success: attempt completed; job completed with counts.
    - Retryable failure with attempts left: attempt retry_scheduled; job back to
      queued with attempt_number + 1 and run_after = now + backoff.
    - Otherwise: attempt failed; job failed with the final error.

    Never re-raises, so one bad job can't kill the worker loop.

    Every log line emitted while the job runs, in any module, carries job_id,
    attempt, item_id and kind (decision 024, 025).
    """
    with job_context(job_id=job.id, attempt=job.attempt_number,
                     item_id=job.plaid_item_id, kind=job.kind):
        log_event(logger, "job_started")
        _run_job(job)


def _run_job(job):
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
    except LeaseLost:
        _log_lease_lost()
        return
    except Exception as e:
        error_code, error_message = _describe_error(e)

        # Retry only allowlisted errors, and only if attempts remain (decisions 010, 013).
        try:
            if is_retryable(e) and job.attempt_number < MAX_ATTEMPTS:
                delay = compute_backoff(job.attempt_number)
                _schedule_retry(job, attempt, error_code, error_message, delay)
                log_event(logger, "retry_scheduled", level=logging.WARNING,
                          error_code=error_code, error=error_message, delay_s=round(delay, 1))
            else:
                _record_failure(job, attempt, error_code, error_message)
                # A traceback only for errors we can't name: those are usually our bugs.
                log_event(logger, "job_failed", level=logging.ERROR,
                          exc_info=e if error_code is None else None,
                          error_code=error_code, error=error_message,
                          retryable=is_retryable(e))
        except LeaseLost:
            # Another worker owns the job now; its outcome is that worker's to record.
            _log_lease_lost()
        return

    duration_s = None
    if job.started_at is not None:
        duration_s = round((timezone.now() - job.started_at).total_seconds(), 2)
    log_event(logger, "job_completed", added=job.added_count,
              modified=job.modified_count, removed=job.removed_count, duration_s=duration_s)


def _log_lease_lost():
    log_event(logger, "lease_lost", level=logging.WARNING,
              detail="another worker reclaimed this job; stopping without writing")


# --- Outcome recording: job and attempt are always updated together ---------
# Each one first confirms (and locks) ownership with renew_lease, so a worker
# that lost its lease can't overwrite the new owner's outcome.

def _record_success(job, attempt):
    now = timezone.now()
    with transaction.atomic():
        renew_lease(job)
        attempt.outcome = SyncAttempt.Outcome.COMPLETED
        attempt.finished_at = now
        attempt.save(update_fields=['outcome', 'finished_at'])

        job.status = SyncJob.Status.COMPLETED
        job.completed_at = now
        job.lease_expires_at = None
        job.save(update_fields=[
            'status', 'completed_at', 'lease_expires_at',
            'added_count', 'modified_count', 'removed_count',
        ])


def _schedule_retry(job, attempt, error_code, error_message, delay_seconds):
    """Close this attempt as retry_scheduled and put the job back in the queue.

    The job stays active (queued), so the one-active-job constraint still holds
    while it waits. The next attempt row is created by claim_next_job.
    """
    now = timezone.now()
    with transaction.atomic():
        renew_lease(job)
        attempt.outcome = SyncAttempt.Outcome.RETRY_SCHEDULED
        attempt.error_code = error_code
        attempt.error_message = error_message
        attempt.finished_at = now
        attempt.save(update_fields=['outcome', 'error_code', 'error_message', 'finished_at'])

        job.status = SyncJob.Status.QUEUED
        job.attempt_number += 1
        job.run_after = now + timedelta(seconds=delay_seconds)
        job.lease_expires_at = None
        job.save(update_fields=[
            'status', 'attempt_number', 'run_after', 'lease_expires_at',
            'added_count', 'modified_count', 'removed_count',
        ])


def _record_failure(job, attempt, error_code, error_message):
    """Close this attempt as failed and fail the job permanently."""
    now = timezone.now()
    with transaction.atomic():
        renew_lease(job)
        attempt.outcome = SyncAttempt.Outcome.FAILED
        attempt.error_code = error_code
        attempt.error_message = error_message
        attempt.finished_at = now
        attempt.save(update_fields=['outcome', 'error_code', 'error_message', 'finished_at'])

        job.status = SyncJob.Status.FAILED
        job.error_code = error_code
        job.error_message = error_message
        job.completed_at = now
        job.lease_expires_at = None
        # Counts are saved on failure too (decision 006): pages committed before the failure count.
        job.save(update_fields=[
            'status', 'error_code', 'error_message', 'completed_at', 'lease_expires_at',
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
