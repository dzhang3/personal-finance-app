from django.urls import reverse
from rest_framework.test import APIClient
import pytest

from app.models import BudgetTarget, User


def client_for(username):
    user = User.objects.create_user(username=username, password='test-pass-123')
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


@pytest.mark.django_db
def test_targets_are_optional_and_scoped_to_the_authenticated_user():
    user, client = client_for('budget_user')

    response = client.get(reverse('budget_targets'))

    assert response.status_code == 200
    assert response.data == {'targets': []}
    assert not BudgetTarget.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_user_can_create_overall_and_category_targets():
    user, client = client_for('budget_create')

    overall = client.put(
        reverse('budget_targets'),
        {'monthly_limit': '2500.00'},
        format='json',
    )
    category = client.put(
        reverse('budget_targets'),
        {'category': 'FOOD_AND_DRINK', 'monthly_limit': '400.50'},
        format='json',
    )

    assert overall.status_code == 200
    assert overall.data == {'category': '', 'monthly_limit': '2500.00'}
    assert category.status_code == 200
    assert category.data == {'category': 'FOOD_AND_DRINK', 'monthly_limit': '400.50'}
    assert BudgetTarget.objects.filter(user=user).count() == 2


@pytest.mark.django_db
def test_user_can_update_and_remove_optional_overall_target():
    user, client = client_for('budget_update')
    BudgetTarget.objects.create(user=user, category='', monthly_limit='2000.00')

    update = client.put(
        reverse('budget_targets'),
        {'category': '', 'monthly_limit': '3000'},
        format='json',
    )
    delete = client.delete(reverse('budget_targets'), {'category': ''}, format='json')

    assert update.status_code == 200
    assert update.data['monthly_limit'] == '3000.00'
    assert delete.status_code == 204
    assert not BudgetTarget.objects.filter(user=user).exists()


@pytest.mark.django_db
@pytest.mark.parametrize('amount', ['0', '-1', 'NaN', 'Infinity', '1.001', '10000000000'])
def test_invalid_monthly_limits_are_rejected(amount):
    _, client = client_for(f'invalid_{amount.replace(".", "_")}')

    response = client.put(
        reverse('budget_targets'),
        {'category': 'FOOD_AND_DRINK', 'monthly_limit': amount},
        format='json',
    )

    assert response.status_code == 400
    assert not BudgetTarget.objects.exists()


@pytest.mark.django_db
def test_user_cannot_view_or_delete_another_users_target():
    owner, _ = client_for('budget_owner')
    _, other_client = client_for('budget_other')
    BudgetTarget.objects.create(user=owner, category='FOOD_AND_DRINK', monthly_limit='400')

    response = other_client.get(reverse('budget_targets'))
    delete = other_client.delete(
        reverse('budget_targets'),
        {'category': 'FOOD_AND_DRINK'},
        format='json',
    )

    assert response.status_code == 200
    assert response.data == {'targets': []}
    assert delete.status_code == 204
    assert BudgetTarget.objects.filter(user=owner, category='FOOD_AND_DRINK').exists()
