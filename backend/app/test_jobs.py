import json
from datetime import timedelta
from unittest.mock import patch

import plaid
import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from urllib3.exceptions import (
    MaxRetryError,
    NewConnectionError,
    ProtocolError,
    ReadTimeoutError,
    SSLError,
)

from app.jobs import (
    BASE_DELAY_SECONDS,
    MAX_ATTEMPTS,
    MAX_DELAY_SECONDS,
    RETRYABLE_PLAID_ERROR_CODES,
    claim_next_job,
    compute_backoff,
    is_retryable,
    run_job,
)
from app.models import User, PlaidItem, SyncJob, SyncAttempt


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
    make_attempt(claimed_job)
    with patch("app.views.sync_item", autospec=True, side_effect=fake_plaid_error()):
        run_job(claimed_job)

    claimed_job.refresh_from_db()
    assert claimed_job.status == SyncJob.Status.FAILED
    assert claimed_job.error_code == "ITEM_LOGIN_REQUIRED"
    assert claimed_job.error_message == "the login details have changed"
    assert claimed_job.completed_at is not None


@pytest.mark.django_db
def test_run_job_records_generic_error(claimed_job):
    make_attempt(claimed_job)
    with patch("app.views.sync_item", autospec=True, side_effect=ValueError("something broke in our code")):
        run_job(claimed_job)

    claimed_job.refresh_from_db()
    assert claimed_job.status == SyncJob.Status.FAILED
    assert claimed_job.error_code is None
    assert claimed_job.error_message == "something broke in our code"
    assert claimed_job.completed_at is not None


@pytest.mark.django_db
def test_run_job_survives_unparseable_plaid_body(claimed_job):
    make_attempt(claimed_job)
    with patch("app.views.sync_item", autospec=True, side_effect=fake_plaid_error(body=None)):
        run_job(claimed_job)  # must not raise

    claimed_job.refresh_from_db()
    assert claimed_job.status == SyncJob.Status.FAILED
    assert claimed_job.error_code is None
    assert claimed_job.error_message  # falls back to str(e): non-empty, not None
    assert claimed_job.completed_at is not None


# ---------------------------------------------------------------------------
# Milestone 3: backoff, retry classification, retry behavior
#
# The run_job tests call run_job(job), so run_job is expected to look up the
# job's current attempt itself: job.attempts.get(attempt_number=job.attempt_number).
# ---------------------------------------------------------------------------

NO_JITTER = lambda: 0.5  # rng midpoint -> jitter factor exactly 1.0
MIN_JITTER = lambda: 0.0  # -> factor (1 - JITTER_FRACTION)
MAX_JITTER = lambda: 0.999999  # -> factor just under (1 + JITTER_FRACTION)


def make_attempt(job, attempt_number=1):
    """An attempt row in the state run_job receives it: started, no outcome yet."""
    return SyncAttempt.objects.create(
        job=job,
        attempt_number=attempt_number,
        started_at=timezone.now(),
    )


# --- compute_backoff (pure function, no DB) --------------------------------

def test_backoff_doubles_from_base():
    assert compute_backoff(1, rng=NO_JITTER) == BASE_DELAY_SECONDS
    assert compute_backoff(2, rng=NO_JITTER) == BASE_DELAY_SECONDS * 2
    assert compute_backoff(3, rng=NO_JITTER) == BASE_DELAY_SECONDS * 4


def test_backoff_never_exceeds_cap():
    # Attempt 20 would be 15 * 2^19 seconds uncapped.
    assert compute_backoff(20, rng=NO_JITTER) == MAX_DELAY_SECONDS
    # Even with maximum jitter, at most 20% over the cap.
    assert compute_backoff(20, rng=MAX_JITTER) <= MAX_DELAY_SECONDS * 1.2


def test_backoff_jitter_stays_within_20_percent():
    assert compute_backoff(1, rng=MIN_JITTER) == pytest.approx(BASE_DELAY_SECONDS * 0.8)
    assert compute_backoff(1, rng=MAX_JITTER) == pytest.approx(BASE_DELAY_SECONDS * 1.2, rel=1e-4)
    for _ in range(100):
        delay = compute_backoff(1)  # real randomness
        assert BASE_DELAY_SECONDS * 0.8 <= delay <= BASE_DELAY_SECONDS * 1.2


# --- is_retryable (pure function, no DB) -----------------------------------

@pytest.mark.parametrize("code", sorted(RETRYABLE_PLAID_ERROR_CODES))
def test_retryable_plaid_errors(code):
    assert is_retryable(fake_plaid_error(error_code=code)) is True


@pytest.mark.parametrize("code", ["ITEM_LOGIN_REQUIRED", "INVALID_ACCESS_TOKEN", "SOME_NEW_UNKNOWN_CODE"])
def test_non_retryable_plaid_errors(code):
    assert is_retryable(fake_plaid_error(error_code=code)) is False


def test_plaid_error_with_unparseable_body_is_not_retryable():
    # No error code means unknown, and the allowlist doesn't retry unknowns.
    assert is_retryable(fake_plaid_error(body=None)) is False


def test_our_own_bug_is_not_retryable():
    assert is_retryable(KeyError("oops")) is False
    assert is_retryable(ValueError("bad data")) is False


def test_wrapped_connection_failure_is_retryable():
    exc = MaxRetryError(pool=None, url="/transactions/sync", reason=NewConnectionError(None, "refused"))
    assert is_retryable(exc) is True


def test_wrapped_ssl_failure_is_not_retryable():
    exc = MaxRetryError(pool=None, url="/transactions/sync", reason=SSLError("bad cert"))
    assert is_retryable(exc) is False


def test_unwrapped_read_timeout_and_dropped_connection_are_retryable():
    assert is_retryable(ReadTimeoutError(pool=None, url="/transactions/sync", message="timed out")) is True
    assert is_retryable(ProtocolError("Connection aborted")) is True


# --- claim_next_job with run_after -----------------------------------------

def _claimed_job(result):
    """claim_next_job may return a job or (job, attempt); normalize to the job."""
    return result[0] if isinstance(result, tuple) else result


@pytest.mark.django_db
def test_claim_skips_job_not_due_yet(user):
    job = SyncJob.objects.create(
        plaid_item=make_item(user, "item_a"),
        run_after=timezone.now() + timedelta(minutes=5),
    )

    assert _claimed_job(claim_next_job()) is None
    job.refresh_from_db()
    assert job.status == SyncJob.Status.QUEUED


@pytest.mark.django_db
def test_claim_takes_job_whose_run_after_has_passed(user):
    job = SyncJob.objects.create(
        plaid_item=make_item(user, "item_a"),
        run_after=timezone.now() - timedelta(seconds=1),
    )

    assert _claimed_job(claim_next_job()) == job


@pytest.mark.django_db
def test_claim_creates_attempt_row(user):
    job = SyncJob.objects.create(plaid_item=make_item(user, "item_a"))

    claimed = _claimed_job(claim_next_job())

    attempts = SyncAttempt.objects.filter(job=job)
    assert claimed == job
    assert attempts.count() == 1
    attempt = attempts.get()
    assert attempt.attempt_number == job.attempt_number
    assert attempt.started_at is not None
    assert attempt.outcome is None  # still running


# --- run_job retry behavior --------------------------------------------------

@pytest.mark.django_db
def test_retryable_error_requeues_job(claimed_job):
    attempt = make_attempt(claimed_job, attempt_number=1)
    with patch("app.views.sync_item", autospec=True, side_effect=fake_plaid_error(error_code="RATE_LIMIT_EXCEEDED")):
        run_job(claimed_job)

    job = SyncJob.objects.get(pk=claimed_job.pk)
    attempt.refresh_from_db()

    # Job is back in the queue for attempt 2, not before its backoff delay.
    assert job.status == SyncJob.Status.QUEUED
    assert job.attempt_number == 2
    assert job.run_after is not None and job.run_after > timezone.now()

    # Attempt 1 records what happened. Attempt 2 does not exist yet:
    # it is created when a worker claims the job again (claim_next_job).
    assert attempt.outcome == SyncAttempt.Outcome.RETRY_SCHEDULED
    assert attempt.error_code == "RATE_LIMIT_EXCEEDED"
    assert attempt.finished_at is not None
    assert SyncAttempt.objects.filter(job=job).count() == 1


@pytest.mark.django_db
def test_non_retryable_error_fails_immediately(claimed_job):
    attempt = make_attempt(claimed_job, attempt_number=1)
    with patch("app.views.sync_item", autospec=True, side_effect=fake_plaid_error(error_code="ITEM_LOGIN_REQUIRED")):
        run_job(claimed_job)

    job = SyncJob.objects.get(pk=claimed_job.pk)
    attempt.refresh_from_db()
    assert SyncAttempt.objects.filter(job=job).count() == 1
    assert job.status == SyncJob.Status.FAILED
    assert job.attempt_number == 1
    assert job.error_code == "ITEM_LOGIN_REQUIRED"
    assert job.run_after is None  # no retry scheduled
    assert attempt.outcome == SyncAttempt.Outcome.FAILED
    assert attempt.error_code == "ITEM_LOGIN_REQUIRED"


@pytest.mark.django_db
def test_retryable_error_on_last_attempt_fails(claimed_job):
    SyncJob.objects.filter(pk=claimed_job.pk).update(attempt_number=MAX_ATTEMPTS)
    claimed_job.refresh_from_db()
    attempt = make_attempt(claimed_job, attempt_number=MAX_ATTEMPTS)
    with patch("app.views.sync_item", autospec=True, side_effect=fake_plaid_error(error_code="RATE_LIMIT_EXCEEDED")):
        run_job(claimed_job)

    job = SyncJob.objects.get(pk=claimed_job.pk)
    attempt.refresh_from_db()
    assert job.status == SyncJob.Status.FAILED
    assert job.attempt_number == MAX_ATTEMPTS
    assert job.error_code == "RATE_LIMIT_EXCEEDED"
    assert attempt.outcome == SyncAttempt.Outcome.FAILED


@pytest.mark.django_db
def test_success_marks_job_and_attempt_completed(claimed_job):
    attempt = make_attempt(claimed_job, attempt_number=1)
    with patch("app.views.sync_item", autospec=True, return_value=None):
        run_job(claimed_job)

    job = SyncJob.objects.get(pk=claimed_job.pk)
    attempt.refresh_from_db()
    assert job.status == SyncJob.Status.COMPLETED
    assert job.completed_at is not None
    assert attempt.outcome == SyncAttempt.Outcome.COMPLETED
    assert attempt.finished_at is not None