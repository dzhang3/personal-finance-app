from datetime import datetime, timezone

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from app.models import Account, PlaidItem, Transaction, User


def make_transaction(username, transaction_id):
    user = User.objects.create_user(username=username, password="test-pass-123")
    item = PlaidItem.objects.create(user=user, item_id=f"item_{username}", access_token="access-sandbox-X")
    account = Account.objects.create(user=user, account_id=f"acc_{username}", plaid_item=item, name="Checking", account_type="bank")
    Transaction.objects.create(
        transaction_id=transaction_id, account=account, amount="12.50",
        datetime=datetime(2026, 1, 1, tzinfo=timezone.utc), transaction_type="FOOD_AND_DRINK",
    )
    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_cannot_edit_another_users_transaction():
    make_transaction("victim", "txn_victim")
    attacker = make_transaction("attacker", "txn_attacker")

    response = client_for(attacker).post(
        reverse("edit_transaction"), {"transaction_id": "txn_victim", "new_amount": "0.01"}, format="json",
    )

    assert response.status_code == 404
    assert str(Transaction.objects.get(transaction_id="txn_victim").amount) == "12.50"


@pytest.mark.django_db
def test_cannot_delete_another_users_transaction():
    make_transaction("victim", "txn_victim")
    attacker = make_transaction("attacker", "txn_attacker")

    response = client_for(attacker).delete(
        reverse("delete_transaction"), {"transaction_id": "txn_victim"}, format="json",
    )

    assert response.status_code == 404
    assert Transaction.objects.filter(transaction_id="txn_victim").exists()


@pytest.mark.django_db
def test_owner_can_edit_and_delete():
    owner = make_transaction("owner", "txn_owner")
    client = client_for(owner)

    edit = client.post(reverse("edit_transaction"), {"transaction_id": "txn_owner", "new_amount": "20.00"}, format="json")
    assert edit.status_code == 200
    assert str(Transaction.objects.get(transaction_id="txn_owner").amount) == "20.00"

    delete = client.delete(reverse("delete_transaction"), {"transaction_id": "txn_owner"}, format="json")
    assert delete.status_code == 200
    assert not Transaction.objects.filter(transaction_id="txn_owner").exists()


@pytest.mark.django_db
def test_changing_transaction_type_marks_it_as_custom():
    owner = make_transaction("category_owner", "txn_category")
    client = client_for(owner)

    response = client.post(
        reverse("edit_transaction"),
        {"transaction_id": "txn_category", "new_category": "GROCERIES"},
        format="json",
    )

    assert response.status_code == 200
    txn = Transaction.objects.get(transaction_id="txn_category")
    assert txn.transaction_type == "GROCERIES"
    assert txn.transaction_type_is_custom is True


@pytest.mark.django_db
def test_editing_other_fields_does_not_mark_category_as_custom():
    owner = make_transaction("amount_owner", "txn_amount")
    client = client_for(owner)

    response = client.post(
        reverse("edit_transaction"),
        {"transaction_id": "txn_amount", "new_amount": "20.00"},
        format="json",
    )

    assert response.status_code == 200
    txn = Transaction.objects.get(transaction_id="txn_amount")
    assert txn.transaction_type_is_custom is False
