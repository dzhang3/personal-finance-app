"""Sync health per Item, served by GET /api/sync_status/ (decisions 026-028).

Never include access_token or Plaid cursor in anything returned from here.
"""
from datetime import timedelta

from django.utils import timezone

from app.jobs import SYNC_INTERVAL
from app.models import SyncJob

# Healthy means a sync succeeded within this window. Two sync intervals, so one
# missed or failed scheduled run doesn't flip the status on its own.
FRESHNESS_WINDOW = 2 * SYNC_INTERVAL
# A job in_progress longer than this means the worker running it died or hung.
# A normal sync takes a few seconds.
STUCK_AFTER = timedelta(minutes=1)


class Reason:
    """Why an Item is (un)healthy. The first one that applies wins."""
    OK = 'ok'
    JOB_STUCK = 'job_stuck'              # in_progress past STUCK_AFTER
    NEVER_SYNCED = 'never_synced'        # no successful sync at all
    STALE = 'stale'                      # last success older than FRESHNESS_WINDOW


# --- Daniel writes this ------------------------------------------------------

def item_status(plaid_item, now=None):
    """Health summary for one Item. Returns a dict shaped like:

        {
            'item_id': 1,
            'institution_name': 'Chase',
            'healthy': False,
            'reason': 'stale',                       # one of Reason.*
            'last_successful_sync_at': <datetime> | None,
            'current_job': _job_summary(job) | None,  # the active (queued/in_progress) job
            'last_error': {'code': ..., 'message': ..., 'at': <datetime>} | None,
        }

    Rules (decision 027):
      - Only kind=sync jobs count toward freshness. A reconcile can succeed
        while the sync path is broken.
      - Unhealthy if the active job has been in_progress longer than STUCK_AFTER.
      - Unhealthy if the latest successful sync is missing or older than
        FRESHNESS_WINDOW.
      - Otherwise healthy.
      - last_error: the most recent failed job of any kind, or None. Decide
        whether an old error should still show after a later success.

    Useful fields: SyncJob.status, .kind, .started_at, .completed_at,
    .error_code, .error_message, .created_at. `now` is injectable for tests.
    """
    now = now or timezone.now()
    latest_success = SyncJob.objects.filter(plaid_item=plaid_item, kind=SyncJob.Kind.SYNC, status=SyncJob.Status.COMPLETED).order_by('-completed_at').first()
    if latest_success:
        last_successful_sync_at = latest_success.completed_at
    else:
        last_successful_sync_at = None

    latest_failure = SyncJob.objects.filter(plaid_item=plaid_item, status=SyncJob.Status.FAILED).order_by('-completed_at').first()
    # if latest failure is after the latest success, include its code/message/at. Otherwise None.
    if latest_failure and (latest_success is None or latest_failure.completed_at > latest_success.completed_at):
        last_error = {
            'code': latest_failure.error_code,
            'message': latest_failure.error_message,
            'at': latest_failure.completed_at,
        }
    else:
        last_error = None

    cur_job = SyncJob.objects.filter(plaid_item=plaid_item, status__in=[SyncJob.Status.QUEUED, SyncJob.Status.IN_PROGRESS]).order_by('-created_at').first()
    if cur_job and cur_job.status == SyncJob.Status.IN_PROGRESS and (now - cur_job.started_at > STUCK_AFTER):
        # in_progress too long
        healthy = False
        reason = Reason.JOB_STUCK
    else:
        healthy = True if last_successful_sync_at and (now - last_successful_sync_at <= FRESHNESS_WINDOW) else False
        if not healthy:
            if latest_success is None:
                reason = Reason.NEVER_SYNCED
            else:
                reason = Reason.STALE
        else:
            reason = Reason.OK

    return {
        'item_id': plaid_item.id,
        'institution_name': plaid_item.institution_name,
        'healthy': healthy,
        'reason': reason,
        'last_successful_sync_at': last_successful_sync_at,
        'current_job': _job_summary(cur_job),
        'last_error': last_error,
    }
    


# --- Serialization helpers ---------------------------------------------------

def _job_summary(job):
    """The fields of a job safe and useful to show. None-safe."""
    if job is None:
        return None
    return {
        'id': job.id,
        'kind': job.kind,
        'status': job.status,
        'attempt': job.attempt_number,
        'created_at': job.created_at,
        'started_at': job.started_at,
        'run_after': job.run_after,
    }


def overall_status(plaid_items, now=None):
    """The endpoint's response body: every Item's status plus one yes/no for alerting."""
    now = now or timezone.now()
    items = [item_status(item, now) for item in plaid_items]
    return {
        'healthy': all(item['healthy'] for item in items),
        'checked_at': now,
        'items': items,
    }
