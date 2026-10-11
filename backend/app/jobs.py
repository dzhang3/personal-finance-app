"""Sync job queue: enqueueing, claiming, and running SyncJobs.

The SyncJob table is the queue (decision 004). One active job per Item is
enforced by a partial unique constraint (decision 008).
"""
import json

from django.utils import timezone

from django.db import IntegrityError, transaction

from app.models import SyncJob

import plaid


def enqueue_sync(plaid_item):
    """Queue a sync for this Item, or return its existing active job.

    The nested atomic() creates a savepoint. If the INSERT violates the
    one-active-job constraint, only the savepoint rolls back, so a caller's
    surrounding transaction (e.g. in exchange_public_token) stays usable.
    """
    try:
        with transaction.atomic():
            return SyncJob.objects.create(plaid_item=plaid_item)
    except IntegrityError:
        return SyncJob.objects.get(
            plaid_item=plaid_item,
            status__in=SyncJob.ACTIVE_STATUSES,
        )


# ---------------------------------------------------------------------------
# Daniel writes these two. Contracts below; the worker loop calls them.
# ---------------------------------------------------------------------------

def claim_next_job():
    """Atomically claim the oldest queued job, or return None if there is none.

    Contract:
    - Two workers calling this at the same time must never get the same job.
    - The claimed job must be marked in_progress, with started_at set, before
      this function returns, and that change must be committed.
    - Returns the SyncJob, or None when the queue is empty.
    """
    with transaction.atomic():
        job = SyncJob.objects.filter(status=SyncJob.Status.QUEUED).order_by('created_at','id').select_for_update(skip_locked=True).first()

        # update job status to in_progress and set started_at
        if job:
            job.status = SyncJob.Status.IN_PROGRESS
            job.started_at = timezone.now()
            job.save(update_fields=['status', 'started_at'])

    return job


def run_job(job):
    """Run one claimed job to completion and record the outcome on the row.

    Contract:
    - On success: status=completed, completed_at set, counts recorded.
    - On any exception: status=failed, completed_at set, error_message (and
      error_code if it came from Plaid) recorded. Must not re-raise, so one
      bad job doesn't kill the worker loop.
    - step should reflect what the job was doing when it failed.
    """
    try:
        from app.views import sync_item
        sync_item(job.plaid_item, job)
        job.status = SyncJob.Status.COMPLETED
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'completed_at', 'added_count', 'modified_count', 'removed_count'])
    except plaid.ApiException as e:
        error_code, error_message = _parse_plaid_error(e)
        _mark_failed(job, error_code=error_code, error_message=error_message)
    except Exception as e:
        _mark_failed(job, error_code=None, error_message=str(e))


def _parse_plaid_error(e):
    """Return (error_code, error_message) from a plaid.ApiException. Never raises.

    Runs inside an exception handler, so it must not be able to fail: a body that
    is missing, not JSON, or not a JSON object falls back to (None, str(e)).
    """
    try:
        body = json.loads(e.body)
    except (TypeError, ValueError):
        body = None
    if not isinstance(body, dict):
        return None, str(e)
    return body.get('error_code'), body.get('error_message') or str(e)


def _mark_failed(job, error_code, error_message):
    job.status = SyncJob.Status.FAILED
    job.error_code = error_code
    job.error_message = error_message
    job.completed_at = timezone.now()
    # Counts are saved on failure too (decision 006): pages committed before the failure count.
    job.save(update_fields=[
        'status', 'error_code', 'error_message', 'completed_at',
        'added_count', 'modified_count', 'removed_count',
    ])
