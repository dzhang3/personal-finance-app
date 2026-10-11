import base64
import os
import datetime as dt
import json
import time
from datetime import date, timedelta, datetime
import uuid
import traceback
import logging

from app.models import User, Account, Transaction, SavingsGoal, Paycheck, MonthlySpending, PlaidItem, SyncJob

from django.shortcuts import render
from django.http import JsonResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from django.forms.models import model_to_dict
from django.db import transaction

from dotenv import load_dotenv
import plaid
from plaid.model.payment_amount import PaymentAmount
from plaid.model.payment_amount_currency import PaymentAmountCurrency
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.user_create_request import UserCreateRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.investments_transactions_get_request_options import InvestmentsTransactionsGetRequestOptions
from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
from plaid.model.institutions_get_request import InstitutionsGetRequest
from plaid.model.link_token_transactions import LinkTokenTransactions
from plaid.model.liabilities_get_request import LiabilitiesGetRequest

from plaid.api import plaid_api

import app.db_methods as db
from app.jobs import enqueue_sync

load_dotenv()

PLAID_CLIENT_ID = os.getenv('PLAID_CLIENT_ID')
PLAID_ENV = os.getenv('PLAID_ENV', 'sandbox')
PLAID_PRODUCTS = os.getenv('PLAID_PRODUCTS', 'transactions').split(',')
PLAID_COUNTRY_CODES = os.getenv('PLAID_COUNTRY_CODES', 'US').split(',')
PLAID_SECRET = os.getenv('PLAID_SECRET_SANDBOX') if os.getenv('PLAID_ENV') == 'sandbox' else os.getenv('PLAID_SECRET_PRODUCTION')


def empty_to_none(field):
    value = os.getenv(field)
    if value is None or len(value) == 0:
        return None
    return value

host = plaid.Environment.Sandbox

if PLAID_ENV == 'sandbox':
    host = plaid.Environment.Sandbox

if PLAID_ENV == 'production':
    host = plaid.Environment.Production

PLAID_REDIRECT_URI = empty_to_none('PLAID_REDIRECT_URI')

configuration = plaid.Configuration(
    host=host,
    api_key={
        'clientId': PLAID_CLIENT_ID,
        'secret': PLAID_SECRET,
        'plaidVersion': '2020-09-14'
    }
)

api_client = plaid.ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)

products = []
for product in PLAID_PRODUCTS:
    products.append(Products(product))

country_codes = list(map(lambda x: CountryCode(x), PLAID_COUNTRY_CODES))


# We store the access_token in memory - in production, store it in a secure
# persistent data store.
access_tokens = {}
access_token = 'access-sandbox-cc744d52-0931-463e-8ead-300630b67a39'
# The payment_id is only relevant for the UK Payment Initiation product.
# We store the payment_id in memory - in production, store it in a secure
# persistent data store.
payment_id = None
# The transfer_id is only relevant for Transfer ACH product.
# We store the transfer_id in memory - in production, store it in a secure
# persistent data store.
transfer_id = None
# We store the user_token in memory - in production, store it in a secure
# persistent data store.
user_token = None

item_id = None

@api_view(['GET'])
@permission_classes([AllowAny])
def check_user_exists(request):
    return JsonResponse({
        'exists': User.objects.exists()
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def has_accounts(request):
    accounts = Account.objects.filter(user=request.user)
    has_accounts = len(accounts) > 0
    print('User has accounts:', has_accounts)
    return JsonResponse({
        'hasAccounts': has_accounts,
    })

# Create your views here.
@api_view(['POST'])
@permission_classes([AllowAny])
def create_user(request):
    try:
        basic_user = User(
            name='Daniel',
            email=None,
            password_hash='password'
        )
        basic_user.save()
        return JsonResponse({
            'user': basic_user.id,
        })
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)

def create_or_get_user(): # for testing purposes
    try:
        user = User.objects.filter(id=1).first()
        if user is None:
            user = User(
                name='Daniel',
                email=None,
                password_hash='password'
            )
            user.save()
        print('user created or found:', user)
        return user
    except Exception as e:
        print('Error in create_or_get_user:', e)
        raise


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def create_link_token(request):
    try:
        request = LinkTokenCreateRequest(
            user = LinkTokenCreateRequestUser(
                client_user_id = str(request.user.id),
            ),
            transactions = LinkTokenTransactions(
                days_requested = 365,
            ),
            products=products,
            client_name='Finance App',
            country_codes=country_codes,
            language='en',
        )
        print('request:', request)
        response = client.link_token_create(request)
        print('Link token created: %s' % response.link_token)
        return JsonResponse(response.to_dict())
    except plaid.ApiException as e:
        print(e)
        return json.loads(e.body)
    


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def exchange_public_token(request):
    public_token = request.data.get('public_token')
    
    if not public_token:
        return JsonResponse({
            'error': 'public_token is required'
        }, status=400)
    
    try:
        # Exchange the public token for an access token
        exchange_request = ItemPublicTokenExchangeRequest(
            public_token=public_token
        )
        exchange_response = client.item_public_token_exchange(exchange_request)
        exchange_response = exchange_response if isinstance(exchange_response, dict) else exchange_response.to_dict()

        access_token = exchange_response['access_token']
        item_id = exchange_response['item_id']

        with transaction.atomic():
            plaid_item = PlaidItem.objects.create(
                user=request.user,
                item_id=item_id,
                access_token=access_token
            )
    
            enqueue_sync(plaid_item)
        
        return Response(status=status.HTTP_202_ACCEPTED)
    except plaid.ApiException as e:
        return JsonResponse(json.loads(e.body), status=500)
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)
    

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_transactions(request):
    # get accounts associated to user
    accounts = Account.objects.filter(user=request.user)
    if len(accounts) == 0:
        return JsonResponse({
            'error': 'No accounts found for user',
            'transactions': []
        })
    # get transactions for each account and combine into json list
    transactions = []
    for acc in accounts:
        transactions.extend([
            {
                'transaction_id': t.transaction_id,
                'amount': float(t.amount),
                'description': t.description,
                'merchant_name': t.merchant_name,
                'datetime': t.datetime.isoformat(),
                'transaction_type': t.transaction_type,
                'payment_channel': t.payment_channel,
                'account': {
                    'name': t.account.name,
                    'account_type': t.account.account_type,
                    'institution': t.account.institution
                }
            }
            for t in Transaction.objects.filter(account=acc).order_by('datetime')
        ])
    
    return JsonResponse({
        'transactions': transactions
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def force_transaction_sync(request):
    plaid_items = PlaidItem.objects.filter(user=request.user)
    for plaid_item in plaid_items:
        enqueue_sync(plaid_item)

    print('Sync jobs queued for user:', request.user.id)
    return Response(status=status.HTTP_202_ACCEPTED)

def sync_item(plaid_item, job, attempt):
    """Sync one Item from Plaid, page by page. Called by the worker's run_job.

    Raises on any failure (plaid.ApiException for Plaid errors) so run_job can
    record it. Saves attempt.step before each phase, so a failure shows where it
    happened. Accumulates counts on the job object; run_job does the final save.

    Known gaps, fixed in later milestones:
    - Pages are not written atomically with the cursor, and writes are not
      idempotent yet (milestone 4).
    - TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION is not handled; it fails the
      job (milestones 3 and 4).
    """
    user = plaid_item.user
    while True:
        attempt.step = SyncJob.Step.FETCH_TRANSACTIONS
        attempt.save(update_fields=['step'])

        request_params = {'access_token': plaid_item.access_token}
        if plaid_item.cursor:
            request_params['cursor'] = plaid_item.cursor
        response = client.transactions_sync(TransactionsSyncRequest(**request_params)).to_dict()

        attempt.step = SyncJob.Step.UPDATE_DB
        attempt.save(update_fields=['step'])

        db.update_accounts(user, plaid_item, response['accounts'])
        db.update_transactions(user, response)

        # Advance the cursor only after this page's writes succeeded.
        plaid_item.cursor = response['next_cursor']
        plaid_item.save(update_fields=['cursor'])

        job.added_count += len(response['added'])
        job.modified_count += len(response['modified'])
        job.removed_count += len(response['removed'])

        if not response['has_more']:
            return
    
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_accounts(request):
    accounts = Account.objects.filter(user=request.user)
    if len(accounts) == 0:
        return JsonResponse({
            'error': 'No accounts found for user',
        })
    return JsonResponse({
        'accounts': [acc.to_dict() for acc in accounts],
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_item(request):
    global access_token
    try:
        request = ItemGetRequest(
            access_token=access_token
        )
        response = client.item_get(request)
        print("Item response:", str(response))
        return JsonResponse(response.to_dict())
    except plaid.ApiException as e:
        return json.loads(e.body)
    
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_liabilities(request):
    try:
        request = LiabilitiesGetRequest(access_token=access_token)
        response = client.liabilities_get(request)
        return JsonResponse(response.to_dict())
    except plaid.ApiException as e:
        return json.loads(e.body)

@api_view(['POST'])
def register_user(request):
    try:
        username = request.data.get('username')
        password = request.data.get('password')
        email = request.data.get('email', '')  # Optional email

        if not username or not password:
            return Response(
                {'error': 'Username and password are required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        if User.objects.filter(username=username).exists():
            return Response(
                {'error': 'Username already exists'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.create_user(
            username=username,
            password=password,
            email=email if email else None
        )
        
        # Log the user in after registration
        login(request, user)
        
        return Response({
            'message': 'User created successfully',
            'user': {
                'username': user.username,
                'email': user.email
            }
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        print('Registration error:', str(e))  # Add logging
        return Response(
            {'error': str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
def login_user(request):
    username = request.data.get('username')
    password = request.data.get('password')

    if not username or not password:
        return Response({'error': 'Username and password are required'}, 
                       status=status.HTTP_400_BAD_REQUEST)

    user = authenticate(username=username, password=password)

    if user is not None:
        login(request, user)
        return Response({
            'message': 'Login successful',
            'user': {
                'username': user.username,
                'email': user.email
            }
        })
    else:
        return Response({'error': 'Invalid credentials'}, 
                       status=status.HTTP_401_UNAUTHORIZED)

@api_view(['POST'])
def logout_user(request):
    logout(request)
    return Response({'message': 'Logged out successfully'})

@ensure_csrf_cookie
@api_view(['GET'])
def get_csrf_token(request):
    return Response({'csrfToken': get_token(request)})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_auth(request):
    return Response({
        'isAuthenticated': True,
        'user': {
            'username': request.user.username,
            'email': request.user.email
        }
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def edit_transaction(request):
    print('edit transaction called', request.data)
    try:
        transaction_id = request.data.get('transaction_id')
        new_name = request.data.get('new_name')
        new_amount = request.data.get('new_amount')
        new_category = request.data.get('new_category')

        if not transaction_id:
            return Response({'error': 'Transaction ID is required'}, status=status.HTTP_400_BAD_REQUEST)

        transaction = Transaction.objects.filter(transaction_id=transaction_id).first()
        if not transaction:
            return Response({'error': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)

        if new_name:
            transaction.merchant_name = new_name
        if new_amount:
            transaction.amount = new_amount
        if new_category:
            transaction.transaction_type = new_category

        transaction.save()

        print("lmao:", model_to_dict(transaction))

        return Response({
            'message': 'Transaction updated successfully',
            'transaction': model_to_dict(transaction)
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print('Error updating transaction:', str(e))
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_transaction(request):
    print('delete transaction called', request.data)
    try:
        transaction_id = request.data.get('transaction_id')

        if not transaction_id:
            return Response({'error': 'Transaction ID is required'}, status=status.HTTP_400_BAD_REQUEST)

        transaction = Transaction.objects.filter(transaction_id=transaction_id).first()
        if not transaction:
            return Response({'error': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)

        transaction.delete()

        return Response({
            'message': 'Transaction deleted successfully'
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print('Error deleting transaction:', str(e))
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    