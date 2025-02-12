from django.urls import path
from . import views

# path: /api/*
urlpatterns = [
    path('create_link_token/', views.create_link_token, name='create_link_token'),
    path('exchange_public_token/', views.exchange_public_token, name='exchange_public_token'),
    path('get_item/', views.get_item, name='get_item'),
    path('get_transactions/', views.get_transactions, name='get_transactions'),
    path('get_liabilities/', views.get_liabilities, name='get_liabilities'),
]