import pytest
from datetime import datetime, timezone
from decimal import Decimal

from app import db_methods as db
from app.models import User, Account, Transaction, PlaidItem


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