import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import plaid

from app import db_methods as db
from app.models import User, Account, Transaction, PlaidItem, SyncJob, SyncAttempt
from app.views import sync_item


@pytest.fixture
def user():
    return User.objects.create_user(username="tester", password="test-pass-123")


@pytest.fixture
def plaid_item(user):
    return PlaidItem.objects.create(
        user=user,
        item_id="item_1",
        access_token="access-sandbox-fake",
        institution_name="Test Bank",
    )


@pytest.fixture
def account(user, plaid_item):
    return Account.objects.create(
        user=user,
        account_id="acc_1",
        plaid_item=plaid_item,
        name="Checking",
        account_type="depository",
    )


@pytest.fixture
def existing_transaction(account):
    return Transaction.objects.create(
        transaction_id="txn_pending_1",
        account=account,
        datetime=datetime(2026, 10, 1, tzinfo=timezone.utc),
        amount=Decimal("12.50"),
        transaction_type="FOOD",
    )


@pytest.mark.django_db
def test_removed_transaction_is_deleted(user, existing_transaction):
    # Shape matches Plaid's /transactions/sync response after .to_dict()
    fake_response = {
        "added": [],
        "modified": [],
        "removed": [
            {"transaction_id": "txn_pending_1", "account_id": "acc_1"},
        ],
    }
    db.update_transactions(user, fake_response)
    assert not Transaction.objects.filter(transaction_id="txn_pending_1").exists()


# ---------------------------------------------------------------------------
# Milestone 4: idempotency
#
# Helpers build dicts shaped like Plaid's /transactions/sync response after
# .to_dict(). Only the fields our code reads are included.
# ---------------------------------------------------------------------------

PLAID_ACCOUNT = {
    "account_id": "acc_1",
    "type": "credit",
    "name": "Checking",
    "balances": {"current": 100.0},
}


def make_txn(transaction_id, amount=10.0, merchant="Coffee Shop"):
    return {
        "transaction_id": transaction_id,
        "account_id": "acc_1",
        "amount": amount,
        "merchant_name": merchant,
        "date": "2026-10-01",
        "datetime": None,
        "personal_finance_category": {"primary": "FOOD_AND_DRINK"},
        "payment_channel": "in store",
    }


def make_page(added=(), modified=(), removed=(), next_cursor="cursor_end", has_more=False):
    return {
        "accounts": [PLAID_ACCOUNT],
        "added": list(added),
        "modified": list(modified),
        "removed": list(removed),
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def as_plaid_response(page):
    """Wrap a dict so sync_item can call .to_dict() on it, like the real SDK model."""
    response = MagicMock()
    response.to_dict.return_value = page
    return response


@pytest.fixture
def job_and_attempt(plaid_item):
    job = SyncJob.objects.create(plaid_item=plaid_item, status=SyncJob.Status.IN_PROGRESS)
    attempt = SyncAttempt.objects.create(job=job, attempt_number=1, started_at=datetime.now(timezone.utc))
    return job, attempt


@pytest.fixture
def fake_plaid():
    """Replaces the Plaid client sync_item uses. Set fake_plaid.transactions_sync.side_effect
    to a list: each item is returned (or raised, if it's an exception) on successive calls."""
    with patch("app.views.client") as client:
        yield client


def requested_cursor(call):
    """The cursor sync_item sent in one recorded transactions_sync call (None if omitted)."""
    request = call.args[0]
    return request.get("cursor") if hasattr(request, "get") else getattr(request, "cursor", None)


@pytest.mark.django_db
def test_same_page_applied_twice_stores_one_copy(user, account):
    page = make_page(added=[make_txn("txn_1"), make_txn("txn_2")])

    db.update_transactions(user, page)
    db.update_transactions(user, page)

    assert Transaction.objects.count() == 2
    assert set(Transaction.objects.values_list("transaction_id", flat=True)) == {"txn_1", "txn_2"}


@pytest.mark.django_db
def test_modified_for_unseen_transaction_creates_it(user, account):
    page = make_page(modified=[make_txn("txn_never_added", amount=42.0)])

    db.update_transactions(user, page)

    txn = Transaction.objects.get(transaction_id="txn_never_added")
    assert txn.amount == Decimal("42.00")


@pytest.mark.django_db
def test_modified_overwrites_existing_row(user, existing_transaction):
    page = make_page(modified=[make_txn("txn_pending_1", amount=99.0, merchant="Posted Name")])

    db.update_transactions(user, page)

    txn = Transaction.objects.get(transaction_id="txn_pending_1")
    assert txn.pk == existing_transaction.pk  # updated in place, not delete + insert
    assert txn.amount == Decimal("99.00")
    assert txn.merchant_name == "Posted Name"
    assert Transaction.objects.count() == 1


@pytest.mark.django_db
def test_failure_mid_pagination_then_retry_has_no_duplicates_or_gaps(
    user, account, plaid_item, job_and_attempt, fake_plaid
):
    job, attempt = job_and_attempt
    page_1 = make_page(added=[make_txn("txn_1"), make_txn("txn_2")], next_cursor="cursor_p1", has_more=True)
    page_2 = make_page(added=[make_txn("txn_3")], next_cursor="cursor_p2", has_more=False)

    # Attempt 1: page 1 succeeds, then Plaid fails on page 2.
    fake_plaid.transactions_sync.side_effect = [
        as_plaid_response(page_1),
        plaid.ApiException(status=500, reason="Internal Server Error"),
    ]
    with pytest.raises(plaid.ApiException):
        sync_item(plaid_item, job, attempt)
    plaid_item.refresh_from_db()

    # The failed sync must not have advanced the cursor (decision 016).
    assert plaid_item.cursor is None

    # Attempt 2 (the retry): Plaid serves both pages from the original cursor.
    fake_plaid.transactions_sync.reset_mock()
    fake_plaid.transactions_sync.side_effect = [
        as_plaid_response(page_1),
        as_plaid_response(page_2),
    ]
    sync_item(plaid_item, job, attempt)
    plaid_item.refresh_from_db()

    calls = fake_plaid.transactions_sync.call_args_list
    # The retry restarts from the original (empty) cursor, as Plaid requires.
    assert requested_cursor(calls[0]) is None
    # No gaps (set) and no duplicates (count).
    assert set(Transaction.objects.values_list("transaction_id", flat=True)) == {"txn_1", "txn_2", "txn_3"}
    assert Transaction.objects.count() == 3
    assert plaid_item.cursor == "cursor_p2"
