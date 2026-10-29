from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from app.models import Account, PlaidItem, ReconcileRepair, SyncAttempt, SyncJob, Transaction, User
from app.reconcile import IncompleteFetchError, compute_diff, reconcile_item

TODAY = timezone.localdate()
IN_WINDOW = TODAY - timedelta(days=5)


# --- Helpers -----------------------------------------------------------------

def plaid_txn(transaction_id, amount=10.0, posted=IN_WINDOW, merchant="Coffee Shop"):
    """A transaction dict shaped like /transactions/get after .to_dict()."""
    return {
        "transaction_id": transaction_id,
        "account_id": "acc_1",
        "amount": amount,
        "date": posted,
        "authorized_date": None,
        "datetime": None,
        "authorized_datetime": None,
        "merchant_name": merchant,
        "name": merchant,
        "pending": False,
        "personal_finance_category": {"primary": "FOOD_AND_DRINK"},
        "payment_channel": "in store",
    }


def local_txn(transaction_id, amount="10.00", posted=IN_WINDOW, merchant="Coffee Shop", account=None):
    """An unsaved Transaction with field types as a DB query would return them."""
    return Transaction(
        transaction_id=transaction_id,
        account=account,
        amount=Decimal(amount),
        posted_date=posted,
        datetime=datetime.combine(posted, datetime.min.time(), tzinfo=dt_timezone.utc),
        merchant_name=merchant,
        transaction_type="FOOD_AND_DRINK",
    )


# --- compute_diff: pure function, no DB --------------------------------------

def test_diff_identical_data_finds_nothing():
    plaid_txns = [plaid_txn("txn_1"), plaid_txn("txn_2")]
    local_txns = [local_txn("txn_1"), local_txn("txn_2")]
    missing, extra, mismatched = compute_diff(plaid_txns, local_txns)
    assert len(missing) == 0
    assert len(extra) == 0
    assert len(mismatched) == 0


def test_diff_finds_missing_extra_and_mismatched():
    plaid_txns = [plaid_txn("txn_missing"), plaid_txn("txn_mismatch", amount=5.00), plaid_txn("txn_ok")]
    local_txns = [local_txn("txn_extra"), local_txn("txn_mismatch", amount="10.00"), local_txn("txn_ok")]
    missing, extra, mismatched = compute_diff(plaid_txns, local_txns)
    assert len(missing) == 1 and missing[0]["transaction_id"] == "txn_missing"
    assert len(extra) == 1 and extra[0].transaction_id == "txn_extra"
    assert len(mismatched) == 1 and mismatched[0][0]["transaction_id"] == "txn_mismatch" and mismatched[0][1].transaction_id == "txn_mismatch"


def test_diff_float_vs_decimal_same_value_is_not_a_mismatch():
    # Plaid sends floats; the DB returns Decimals. Equal values must not trigger a repair.
    plaid_txns = [plaid_txn("txn_float_decimal", amount=10.1)]
    local_txns = [local_txn("txn_float_decimal", amount="10.10")]
    missing, extra, mismatched = compute_diff(plaid_txns, local_txns)
    assert len(missing) == 0
    assert len(extra) == 0
    assert len(mismatched) == 0


# --- reconcile_item end to end, Plaid faked ---------------------------------

@pytest.fixture
def user():
    return User.objects.create_user(username="tester", password="test-pass-123")


@pytest.fixture
def plaid_item(user):
    return PlaidItem.objects.create(user=user, item_id="item_1", access_token="access-sandbox-fake")


@pytest.fixture
def account(user, plaid_item):
    return Account.objects.create(
        user=user, account_id="acc_1", plaid_item=plaid_item, name="Card", account_type="credit",
    )


@pytest.fixture
def job_and_attempt(plaid_item):
    job = SyncJob.objects.create(
        plaid_item=plaid_item, kind=SyncJob.Kind.RECONCILE, status=SyncJob.Status.IN_PROGRESS,
    )
    attempt = SyncAttempt.objects.create(job=job, attempt_number=1, started_at=timezone.now())
    return job, attempt


def plaid_get_response(transactions, total=None):
    response = MagicMock()
    response.to_dict.return_value = {
        "accounts": [{"account_id": "acc_1", "type": "credit", "name": "Card", "balances": {"current": 50.0}}],
        "transactions": transactions,
        "total_transactions": len(transactions) if total is None else total,
    }
    return response


@pytest.fixture
def fake_plaid():
    with patch("app.views.client") as client:
        yield client


@pytest.mark.django_db
def test_reconcile_repairs_drift_and_records_it(account, plaid_item, job_and_attempt, fake_plaid):
    job, attempt = job_and_attempt
    local_txn("txn_ok", account=account).save()
    local_txn("txn_wrong_amount", amount="5.00", account=account).save()
    local_txn("txn_gone", account=account).save()
    local_txn("txn_outside_window", posted=TODAY - timedelta(days=90), account=account).save()

    fake_plaid.transactions_get.return_value = plaid_get_response([
        plaid_txn("txn_ok"),
        plaid_txn("txn_wrong_amount", amount=7.25),
        plaid_txn("txn_missing"),
    ])

    reconcile_item(plaid_item, job, attempt)

    ids = set(Transaction.objects.values_list("transaction_id", flat=True))
    # Missing inserted, extra deleted, rows outside the window untouched.
    assert ids == {"txn_ok", "txn_wrong_amount", "txn_missing", "txn_outside_window"}
    assert Transaction.objects.get(transaction_id="txn_wrong_amount").amount == Decimal("7.25")

    repairs = {r.transaction_id: r.action for r in ReconcileRepair.objects.filter(job=job)}
    assert repairs == {
        "txn_missing": ReconcileRepair.Action.INSERTED,
        "txn_wrong_amount": ReconcileRepair.Action.UPDATED,
        "txn_gone": ReconcileRepair.Action.DELETED,
    }
    assert (job.added_count, job.modified_count, job.removed_count) == (1, 1, 1)


@pytest.mark.django_db
def test_incomplete_fetch_fails_without_touching_data(account, plaid_item, job_and_attempt, fake_plaid):
    job, attempt = job_and_attempt
    local_txn("txn_1", account=account).save()
    # Plaid reports 2 transactions but every page returns the same one, like an
    # offset shift mid-fetch. Reconciling this list would delete txn_1.
    fake_plaid.transactions_get.return_value = plaid_get_response([plaid_txn("txn_other")], total=2)

    with pytest.raises(IncompleteFetchError):
        reconcile_item(plaid_item, job, attempt)

    assert set(Transaction.objects.values_list("transaction_id", flat=True)) == {"txn_1"}
    assert not ReconcileRepair.objects.exists()
