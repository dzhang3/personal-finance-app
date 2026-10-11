import json
from datetime import timedelta
from unittest.mock import patch

import plaid
import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from app.jobs import claim_next_job, run_job
from app.models import User, PlaidItem, SyncJob


@pytest.fixture
def user():
    return User.objects.create_user(username="tester", password="test-pass-123")


@pytest.fixture
def other_user():
    return User.objects.create_user(username="someone_else", password="test-pass-123")


@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def make_item(user, item_id):
    return PlaidItem.objects.create(
        user=user,
        item_id=item_id,
        access_token=f"access-sandbox-{item_id}",
    )


@pytest.mark.django_db
def test_force_sync_queues_one_job_per_item(api_client, user):
    # Items with no accounts yet: covers banks whose first sync never ran
    item_a = make_item(user, "item_a")
    item_b = make_item(user, "item_b")

    response = api_client.get(reverse("force_transaction_sync"))

    assert response.status_code == 202
    jobs = SyncJob.objects.all()
    assert jobs.count() == 2
    assert {job.plaid_item_id for job in jobs} == {item_a.id, item_b.id}
    assert all(job.status == SyncJob.Status.QUEUED for job in jobs)
    assert all(job.started_at is None for job in jobs)


@pytest.mark.django_db
def test_force_sync_ignores_other_users_items(api_client, user, other_user):
    make_item(user, "mine")
    make_item(other_user, "not_mine")

    api_client.get(reverse("force_transaction_sync"))

    assert SyncJob.objects.count() == 1
    assert SyncJob.objects.get().plaid_item.user == user


@pytest.mark.django_db
def test_force_sync_requires_login(user):
    make_item(user, "item_a")

    response = APIClient().get(reverse("force_transaction_sync"))

    assert response.status_code in (401, 403)
    assert SyncJob.objects.count() == 0


# ---------------------------------------------------------------------------
# claim_next_job
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_claim_returns_none_when_queue_empty():
    job = claim_next_job()
    assert job is None


@pytest.mark.django_db
def test_claims_return_different_jobs_oldest_first(user):
    # Two Items, because the one-active-job constraint allows only one queued job per Item.
    older = SyncJob.objects.create(plaid_item=make_item(user, "item_a"))
    newer = SyncJob.objects.create(plaid_item=make_item(user, "item_b"))
    # created_at is auto_now_add, so force a clear gap to make "oldest" unambiguous.
    SyncJob.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(minutes=5))

    job1 = claim_next_job()
    job2 = claim_next_job()
    assert job1 == older
    assert job2 == newer
    assert claim_next_job() is None  # queue fully drained


@pytest.mark.django_db
def test_claimed_job_is_in_progress_with_started_at(user):
    job = SyncJob.objects.create(plaid_item=make_item(user, "item_a"))

    claimed_job = claim_next_job()
    claimed_job.refresh_from_db()
    assert claimed_job == job
    assert claimed_job.status == SyncJob.Status.IN_PROGRESS
    assert claimed_job.started_at is not None


# ---------------------------------------------------------------------------
# run_job failure paths
# ---------------------------------------------------------------------------

def fake_plaid_error(error_code="ITEM_LOGIN_REQUIRED", error_message="the login details have changed", body="default"):
    """Build a plaid.ApiException shaped like a real Plaid error response.

    Pass body=None (or any string) to simulate a response whose body isn't valid JSON.
    """
    exc = plaid.ApiException(status=400, reason="Bad Request")
    if body == "default":
        exc.body = json.dumps({"error_code": error_code, "error_message": error_message})
    else:
        exc.body = body
    return exc


@pytest.fixture
def claimed_job(user):
    """A job in the state run_job receives it: already claimed by the worker."""
    return SyncJob.objects.create(
        plaid_item=make_item(user, "item_a"),
        status=SyncJob.Status.IN_PROGRESS,
        started_at=timezone.now(),
    )


# run_job imports sync_item from app.views at call time, so patching it there
# swaps in the fake for the duration of the `with` block.

@pytest.mark.django_db
def test_run_job_records_plaid_error(claimed_job):
    with patch("app.views.sync_item", side_effect=fake_plaid_error()):
        run_job(claimed_job)

    claimed_job.refresh_from_db()
    assert claimed_job.status == SyncJob.Status.FAILED
    assert claimed_job.error_code == "ITEM_LOGIN_REQUIRED"
    assert claimed_job.error_message == "the login details have changed"
    assert claimed_job.completed_at is not None


@pytest.mark.django_db
def test_run_job_records_generic_error(claimed_job):
    with patch("app.views.sync_item", side_effect=ValueError("something broke in our code")):
        run_job(claimed_job)

    claimed_job.refresh_from_db()
    assert claimed_job.status == SyncJob.Status.FAILED
    assert claimed_job.error_code is None
    assert claimed_job.error_message == "something broke in our code"
    assert claimed_job.completed_at is not None


@pytest.mark.django_db
def test_run_job_survives_unparseable_plaid_body(claimed_job):
    with patch("app.views.sync_item", side_effect=fake_plaid_error(body=None)):
        run_job(claimed_job)  # must not raise

    claimed_job.refresh_from_db()
    assert claimed_job.status == SyncJob.Status.FAILED
    assert claimed_job.error_code is None
    assert claimed_job.error_message  # falls back to str(e): non-empty, not None
    assert claimed_job.completed_at is not None