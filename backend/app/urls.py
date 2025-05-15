from django.urls import path
from . import views

# path: /api/*
urlpatterns = [
    # Auth endpoints
    path('auth/register/', views.register_user, name='register'),
    path('auth/login/', views.login_user, name='login'),
    path('auth/logout/', views.logout_user, name='logout'),
    path('auth/csrf/', views.get_csrf_token, name='csrf'),
    path('auth/check/', views.check_auth, name='check_auth'),
    
    # Existing endpoints
    path('check_user_exists/', views.check_user_exists, name='check_user_exists'),
    path('check_has_accounts/', views.has_accounts, name='check_has_accounts'),
    path('create_link_token/', views.create_link_token, name='create_link_token'),
    path('exchange_public_token/', views.exchange_public_token, name='exchange_public_token'),
    path('get_item/', views.get_item, name='get_item'),
    path('get_transactions/', views.get_transactions, name='get_transactions'),
    path('get_liabilities/', views.get_liabilities, name='get_liabilities'),
    path('create_user/', views.create_user, name='create_user'),
    path('get_accounts/', views.get_accounts, name='get_accounts'),
    path('force_transaction_sync/', views.force_transaction_sync, name='force_transaction_sync'),
    path('edit_transaction/', views.edit_transaction, name='edit_transaction'),
    path('delete_transaction/', views.delete_transaction, name='delete_transaction'),
]