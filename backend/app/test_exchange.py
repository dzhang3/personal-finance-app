from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from app.models import PlaidItem, User


@pytest.fixture
def client():
    user = User.objects.create_user(username="tester", password="test-pass-123")
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def exchange(client, body):
    plaid_response = {'access_token': 'access-sandbox-SECRET', 'item_id': 'item_1'}
    with patch('app.views.client.item_public_token_exchange', return_value=plaid_response), \
         patch('app.views.enqueue_sync'):
        return client.post(reverse("exchange_public_token"), body, format="json")


@pytest.mark.django_db
def test_stores_institution_name(client):
    response = exchange(client, {"public_token": "public-sandbox-1", "institution_name": "  Chase  "})

    assert response.status_code == 202
    assert response.content == b""
    assert PlaidItem.objects.get(item_id="item_1").institution_name == "Chase"


@pytest.mark.django_db
def test_institution_name_is_optional(client):
    response = exchange(client, {"public_token": "public-sandbox-1"})

    assert response.status_code == 202
    assert PlaidItem.objects.get(item_id="item_1").institution_name is None
