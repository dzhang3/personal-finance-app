import base64
import os
import datetime as dt
import json
import time
from datetime import date, timedelta, datetime
import uuid
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from app.models import User, Account, Transaction, NetWorthHistory, AccountBalanceHistory, Liability, SavingsGoal, Paycheck, MonthlySpending, Cursor

def update_accounts(user, access_token, accounts):
    for acc in accounts:
        if (acc['type'] != 'credit' or acc['type'] != 'loan'):
            Account.objects.update_or_create(
                user=user,
                account_id=acc['account_id'],
                access_token=access_token,
                name=acc['name'],
                defaults={
                    'account_type': acc['type'],
                    'balance': acc['balances']['current'],
                    'institution': acc.get('institution_name', 'Unknown'),
                },
            )

def update_cursor(user, access_token, cursor):
    # update or create cursor where user and access_id match
    Cursor.objects.update_or_create(
        user=user,
        access_token=access_token,
        defaults={'cursor': cursor},
    )

def update_transactions(user, transactions):
    # Initialize accounts dictionary for caching Account objects
    accounts = {}
    add_transactions(transactions['added'], accounts, user)
    modify_transactions(transactions['modified'], accounts, user)
    remove_transactions(transactions['removed'])
    
def get_account_transactions(account, start_date, end_date):
    return Transaction.objects.filter(account=account, datetime__gte=start_date, datetime__lte=end_date).order_by('datetime')

def add_transactions(transactions_data, accounts, user):
    """Add new transactions to the database."""
    try:
        # Filter out non-expense transactions (only keep positive amounts)
        expense_transactions = [t for t in transactions_data if t.get('amount', 0) > 0]
        
        # Get any account IDs we don't have cached yet
        missing_account_ids = {t['account_id'] for t in expense_transactions} - accounts.keys()
        if missing_account_ids:
            new_accounts = Account.objects.filter(account_id__in=missing_account_ids)
            # Update our accounts cache with the new accounts
            accounts.update({acc.account_id: acc for acc in new_accounts})
        
        transactions = []
        for transaction in expense_transactions:
            # Get the account object from our mapping
            account = accounts.get(transaction['account_id'])
            if not account:
                print(f"Account not found for transaction {transaction['transaction_id']}")
                continue
            
            # Handle datetime with proper timezone awareness
            if transaction.get('datetime') is None:
                # Convert date to datetime at midnight in the current timezone
                date_obj = transaction['date']
                if isinstance(date_obj, str):
                    date_obj = datetime.strptime(date_obj, '%Y-%m-%d').date()
                transaction_datetime = timezone.make_aware(datetime.combine(date_obj, datetime.min.time()))
            else:
                # Parse datetime string and ensure it's timezone aware
                dt_obj = parse_datetime(transaction['datetime'])
                transaction_datetime = timezone.make_aware(dt_obj) if timezone.is_naive(dt_obj) else dt_obj
                
            # Create transaction object
            transaction_obj = Transaction(
                transaction_id=transaction['transaction_id'],
                account=account,
                amount=transaction['amount'],
                description=transaction.get('description', ''),
                merchant_name=transaction.get('merchant_name'),
                datetime=transaction_datetime,
                transaction_type=transaction.get('personal_finance_category', 'UNCATEGORIZED').get('primary', 'UNCATEGORIZED'),
                payment_channel=transaction.get('payment_channel', 'OTHER')
            )
            transactions.append(transaction_obj)

        # Bulk create transactions
        print(f"Adding {len(transactions)} transactions")
        Transaction.objects.bulk_create(transactions)
        return True
    except Exception as e:
        print(f"Error adding transactions: {str(e)}")
        return False

def modify_transactions(transactions_data, accounts, user):
    """Modify existing transactions in the database."""
    try:
        # Filter out non-expense transactions (only keep positive amounts)
        expense_transactions = [t for t in transactions_data if t.get('amount', 0) > 0]
        
        # Get any account IDs we don't have cached yet
        missing_account_ids = {t['account_id'] for t in expense_transactions} - accounts.keys()
        if missing_account_ids:
            new_accounts = Account.objects.filter(account_id__in=missing_account_ids)
            # Update our accounts cache with the new accounts
            accounts.update({acc.account_id: acc for acc in new_accounts})
        
        for transaction in expense_transactions:
            account = accounts.get(transaction['account_id'])
            if not account:
                print(f"Account not found for transaction {transaction['transaction_id']}")
                continue
                
            # Handle datetime with proper timezone awareness
            if transaction.get('datetime') is None:
                # Convert date to datetime at midnight in the current timezone
                date_obj = transaction['date']
                if isinstance(date_obj, str):
                    date_obj = datetime.strptime(date_obj, '%Y-%m-%d').date()
                transaction_datetime = timezone.make_aware(datetime.combine(date_obj, datetime.min.time()))
            else:
                # Parse datetime string and ensure it's timezone aware
                dt_obj = parse_datetime(transaction['datetime'])
                transaction_datetime = timezone.make_aware(dt_obj) if timezone.is_naive(dt_obj) else dt_obj
                
            Transaction.objects.filter(
                transaction_id=transaction['transaction_id']
            ).update(
                account=account,
                amount=transaction['amount'],
                description=transaction.get('description', ''),
                merchant_name=transaction.get('merchant_name'),
                datetime=transaction_datetime,
                transaction_type=transaction.get('personal_finance_category', 'UNCATEGORIZED').get('primary', 'UNCATEGORIZED'),
                payment_channel=transaction.get('payment_channel', 'OTHER')
            )
        return True
    except Exception as e:
        print(f"Error modifying transactions: {str(e)}")
        return False

def remove_transactions(transactions):
    print('removing transactions')
    Transaction.objects.filter(transaction_id__in=transactions).delete()

def get_cursor(access_token):
    try:
        cursor = Cursor.objects.get(access_token=access_token)
        return cursor.cursor
    except Cursor.DoesNotExist:
        return None
