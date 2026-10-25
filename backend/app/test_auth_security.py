import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from app.models import User


@pytest.mark.django_db
def test_authentication_mutations_require_csrf():
    client = APIClient(enforce_csrf_checks=True)

    register = client.post(reverse('register'), {}, format='json')
    login = client.post(reverse('login'), {}, format='json')
    logout = client.post(reverse('logout'), {}, format='json')

    assert register.status_code == 403
    assert login.status_code == 403
    assert logout.status_code == 403


@pytest.mark.django_db
def test_login_succeeds_with_csrf_token():
    User.objects.create_user(username='csrf_user', password='test-pass-123')
    client = APIClient(enforce_csrf_checks=True)
    csrf_response = client.get(reverse('csrf'))

    response = client.post(
        reverse('login'),
        {'username': 'csrf_user', 'password': 'test-pass-123'},
        format='json',
        HTTP_X_CSRFTOKEN=csrf_response.data['csrfToken'],
    )

    assert response.status_code == 200


@pytest.mark.django_db
def test_unsupported_plaid_item_endpoints_do_not_call_plaid():
    user = User.objects.create_user(username='unsupported_user', password='test-pass-123')
    client = APIClient()
    client.force_authenticate(user=user)

    assert client.get('/api/get_item/').status_code == 501
    assert client.get('/api/get_liabilities/').status_code == 501
