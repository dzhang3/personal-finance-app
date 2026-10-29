"""Leases and fencing (decision 030)."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from app.jobs import MAX_ATTEMPTS, LeaseLost, claim_next_job, renew_lease, run_job
from app.models import PlaidItem, SyncAttempt, SyncJob, User


@pytest.fixture
def plaid_item():
    user = User.objects.create_user(username="tester", password="test-pass-123")
    return PlaidItem.objects.create(user=user, item_id="item_1", access_token="access-sandbox-fake")


def running_job(plaid_item, lease_in, attempt_number=1):
    """A job a worker claimed, as it sits in the DB. lease_in: timedelta from now
    (negative = already expired), or None for a pre-lease row."""
    now = timezone.now()
    job = SyncJob.objects.create(
        plaid_item=plaid_item,
        status=SyncJob.Status.IN_PROGRESS,
        attempt_number=attempt_number,
        started_at=now - timedelta(minutes=5),
        lease_expires_at=None if lease_in is None else now + lease_in,
    )
    SyncAttempt.objects.create(job=job, attempt_number=attempt_number, started_at=job.started_at)
    return job


@pytest.mark.django_db
def test_job_with_live_lease_is_not_claimable(plaid_item):
    running_job(plaid_item, lease_in=timedelta(seconds=30))
    assert claim_next_job() is None


@pytest.mark.django_db
def test_expired_lease_is_reclaimed_as_a_new_attempt(plaid_item):
    job = running_job(plaid_item, lease_in=timedelta(seconds=-1))

    claimed = claim_next_job()

    assert claimed.id == job.id
    assert claimed.status == SyncJob.Status.IN_PROGRESS
    assert claimed.attempt_number == 2
    assert claimed.lease_expires_at > timezone.now()
    old, new = SyncAttempt.objects.filter(job=job).order_by("attempt_number")
    assert old.outcome == SyncAttempt.Outcome.LEASE_EXPIRED and old.finished_at is not None
    assert new.attempt_number == 2 and new.outcome is None


@pytest.mark.django_db
def test_in_progress_job_from_before_leases_is_reclaimed(plaid_item):
    # Like job 33 from the baseline kill test: in_progress with no lease at all.
    job = running_job(plaid_item, lease_in=None)
    assert claim_next_job().id == job.id


@pytest.mark.django_db
def test_renew_extends_the_lease_for_the_owner(plaid_item):
    job = running_job(plaid_item, lease_in=timedelta(seconds=5))
    renew_lease(job)
    job.refresh_from_db()
    assert job.lease_expires_at > timezone.now() + timedelta(seconds=30)


@pytest.mark.django_db
def test_old_worker_is_fenced_out_after_reclaim(plaid_item):
    stale_view = running_job(plaid_item, lease_in=timedelta(seconds=-1))  # the frozen worker's copy
    claim_next_job()  # a live worker takes over as attempt 2

    with pytest.raises(LeaseLost):
        renew_lease(stale_view)


@pytest.mark.django_db
def test_old_worker_cannot_record_an_outcome_after_reclaim(plaid_item):
    stale_view = running_job(plaid_item, lease_in=timedelta(seconds=-1))
    claim_next_job()

    # The frozen worker wakes up and "finishes" its sync.
    with patch("app.views.sync_item", autospec=True, return_value=None):
        run_job(stale_view)

    job = SyncJob.objects.get(pk=stale_view.pk)
    assert job.status == SyncJob.Status.IN_PROGRESS  # still the new owner's
    assert job.attempt_number == 2
    assert SyncAttempt.objects.get(job=job, attempt_number=2).outcome is None
    assert SyncAttempt.objects.get(job=job, attempt_number=1).outcome == SyncAttempt.Outcome.LEASE_EXPIRED


@pytest.mark.django_db
def test_job_abandoned_too_many_times_fails_instead_of_looping(plaid_item):
    job = running_job(plaid_item, lease_in=timedelta(seconds=-1), attempt_number=MAX_ATTEMPTS)

    assert claim_next_job() is None

    job.refresh_from_db()
    assert job.status == SyncJob.Status.FAILED
    assert job.error_code == "LEASE_EXPIRED_MAX_ATTEMPTS"
