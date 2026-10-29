from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from app.models import PlaidItem, SyncJob, User
from app.status import FRESHNESS_WINDOW, STUCK_AFTER, Reason, item_status

NOW = timezone.now()


@pytest.fixture
def user():
    return User.objects.create_user(username="tester", password="test-pass-123")


@pytest.fixture
def plaid_item(user):
    return PlaidItem.objects.create(
        user=user, item_id="item_1", access_token="access-sandbox-SECRET", institution_name="Test Bank",
    )


def make_job(plaid_item, kind=SyncJob.Kind.SYNC, status=SyncJob.Status.COMPLETED,
             started_ago=None, completed_ago=None, error_code=None):
    """A job as the worker would leave it. *_ago are timedeltas before NOW."""
    return SyncJob.objects.create(
        plaid_item=plaid_item,
        kind=kind,
        status=status,
        started_at=NOW - started_ago if started_ago is not None else None,
        completed_at=NOW - completed_ago if completed_ago is not None else None,
        error_code=error_code,
        error_message=f"{error_code} happened" if error_code else None,
    )


# --- item_status rules ----------------------------------------------------------

@pytest.mark.django_db
def test_never_synced_is_unhealthy(plaid_item):
    status = item_status(plaid_item, now=NOW)
    assert status["healthy"] is False
    assert status["reason"] == Reason.NEVER_SYNCED


@pytest.mark.django_db
def test_recent_successful_sync_is_healthy(plaid_item):
    make_job(plaid_item, completed_ago=timedelta(minutes=30), started_ago=timedelta(minutes=30))
    status = item_status(plaid_item, now=NOW)
    assert status["healthy"] is True
    assert status["reason"] == Reason.OK


@pytest.mark.django_db
def test_sync_older_than_window_is_stale(plaid_item):
    make_job(plaid_item, completed_ago=FRESHNESS_WINDOW + timedelta(minutes=1), started_ago=FRESHNESS_WINDOW + timedelta(minutes=1))
    status = item_status(plaid_item, now=NOW)
    assert status["healthy"] is False
    assert status["reason"] == Reason.STALE


@pytest.mark.django_db
def test_recent_reconcile_does_not_count_as_fresh(plaid_item):
    make_job(plaid_item, kind=SyncJob.Kind.SYNC, completed_ago=FRESHNESS_WINDOW + timedelta(minutes=1), started_ago=FRESHNESS_WINDOW + timedelta(minutes=1))
    make_job(plaid_item, kind=SyncJob.Kind.RECONCILE, completed_ago=timedelta(minutes=5), started_ago=timedelta(minutes=5))
    status = item_status(plaid_item, now=NOW)
    assert status["healthy"] is False
    assert status["reason"] == Reason.STALE


@pytest.mark.django_db
def test_job_in_progress_too_long_is_stuck_even_if_data_is_fresh(plaid_item):
    make_job(plaid_item, completed_ago=None, started_ago=STUCK_AFTER + timedelta(minutes=1), status=SyncJob.Status.IN_PROGRESS)
    make_job(plaid_item, completed_ago=timedelta(minutes=5), started_ago=timedelta(minutes=5))
    status = item_status(plaid_item, now=NOW)
    assert status["healthy"] is False
    assert status["reason"] == Reason.JOB_STUCK


@pytest.mark.django_db
def test_failure_before_latest_success_is_hidden(plaid_item):
    make_job(plaid_item, completed_ago=timedelta(minutes=30), started_ago=timedelta(minutes=30))
    make_job(plaid_item, completed_ago=timedelta(minutes=60), started_ago=timedelta(minutes=60), status=SyncJob.Status.FAILED, error_code="E1")
    status = item_status(plaid_item, now=NOW)
    assert status["healthy"] is True
    assert status["reason"] == Reason.OK
    assert status["last_error"] is None


@pytest.mark.django_db
def test_failure_after_latest_success_is_shown(plaid_item):
    # A failed reconcile after a good sync: shown, but doesn't affect health (decision 027).
    make_job(plaid_item, completed_ago=timedelta(minutes=60), started_ago=timedelta(minutes=60))
    make_job(plaid_item, kind=SyncJob.Kind.RECONCILE, completed_ago=timedelta(minutes=30), started_ago=timedelta(minutes=30), status=SyncJob.Status.FAILED, error_code="E2")
    status = item_status(plaid_item, now=NOW)
    assert status["healthy"] is True
    assert status["reason"] == Reason.OK
    assert status["last_error"] == {
        'code': "E2",
        'message': "E2 happened",
        'at': NOW - timedelta(minutes=30),
    }


# --- Endpoint ------------------------------------------------------------------

@pytest.mark.django_db
def test_endpoint_returns_only_my_items_and_never_the_access_token(user, plaid_item):
    other = User.objects.create_user(username="someone_else", password="test-pass-123")
    PlaidItem.objects.create(user=other, item_id="item_other", access_token="access-sandbox-OTHER")
    make_job(plaid_item, completed_ago=timedelta(hours=1), started_ago=timedelta(hours=1))

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get(reverse("sync_status"))

    assert response.status_code == 200
    body = response.json()
    assert [item["item_id"] for item in body["items"]] == [plaid_item.id]
    assert body["healthy"] is True
    assert "access-sandbox" not in response.content.decode()


@pytest.mark.django_db
def test_endpoint_requires_login():
    response = APIClient().get(reverse("sync_status"))
    assert response.status_code in (401, 403)
