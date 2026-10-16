import base64
import os
import datetime as dt
import json
import time
from datetime import date, timedelta, datetime
import uuid
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import logging
from app.logging_utils import log_event
logger = logging.getLogger(__name__)

from app.models import User, Account, Transaction, SavingsGoal, Paycheck, MonthlySpending, PlaidItem

def update_accounts(user, plaid_item, accounts):
    for acc in accounts:
        Account.objects.update_or_create(
            user=user,
            account_id=acc['account_id'],
            plaid_item=plaid_item,
            defaults={
                'account_type': acc['type'],
                'balance': acc['balances']['current'],
                'institution': acc.get('institution_name', 'Unknown'),
                'name': acc['name'],
            }
        )

def update_transactions(user, transactions):
    # Initialize accounts dictionary for caching Account objects
    accounts = {}
    upsert_transactions(transactions['added'], accounts, user)
    upsert_transactions(transactions['modified'], accounts, user)
    remove_transactions([r['transaction_id'] for r in transactions['removed']])
    
def get_account_transactions(account, start_date, end_date):
    return Transaction.objects.filter(account=account, datetime__gte=start_date, datetime__lte=end_date).order_by('datetime')

def upsert_transactions(transactions_data, accounts, user):
    """Insert new transactions or overwrite existing ones, keyed on transaction_id (decisions 014, 015)."""
    # Get any account IDs we don't have cached yet
    missing_account_ids = {t['account_id'] for t in transactions_data} - accounts.keys()
    if missing_account_ids:
        new_accounts = Account.objects.filter(account_id__in=missing_account_ids)
        # Update our accounts cache with the new accounts
        accounts.update({acc.account_id: acc for acc in new_accounts})
    
    transactions = []
    for transaction in transactions_data:
        # Get the account object from our mapping
        account = accounts.get(transaction['account_id'])
        if not account:
            log_event(logger, "account_not_found", level=logging.WARNING, transaction_id=transaction['transaction_id'], account_id=transaction['account_id'])
            continue
        
        transaction_datetime = _purchase_datetime(transaction)
        posted_date = _as_date(transaction['date'])

        # Create transaction object
        transaction_obj = Transaction(
            transaction_id=transaction['transaction_id'],
            account=account,
            amount=transaction['amount'],
            description=transaction.get('name', ''),
            merchant_name=transaction.get('merchant_name'),
            datetime=transaction_datetime,
            posted_date=posted_date,
            transaction_type=(transaction.get('personal_finance_category') or {}).get('primary', 'UNCATEGORIZED'),
            payment_channel=transaction.get('payment_channel', 'OTHER')
        )
        transactions.append(transaction_obj)

    # Bulk create transactions
    Transaction.objects.bulk_create(transactions, update_conflicts=True, unique_fields=['transaction_id'], update_fields=['account', 'amount', 'description', 'merchant_name', 'datetime', 'posted_date', 'transaction_type', 'payment_channel'])
    log_event(logger, "transactions_upserted", level=logging.DEBUG, count=len(transactions))
    return True


def _as_date(value):
    """A datetime.date from the SDK's date object or a 'YYYY-MM-DD' string."""
    if isinstance(value, str):
        return datetime.strptime(value, '%Y-%m-%d').date()
    return value


def _purchase_datetime(transaction):
    """When the purchase happened, as an aware datetime.

    Prefers authorization (when the purchase was made) over posting. Each field
    can be null depending on the institution, so fall back in order:
    authorized_datetime -> authorized_date -> datetime -> date (always present).
    Date-only values become midnight in TIME_ZONE.
    """
    if transaction.get('authorized_datetime'):
        return _aware(transaction['authorized_datetime'])
    if transaction.get('authorized_date'):
        return _midnight(transaction['authorized_date'])
    if transaction.get('datetime'):
        return _aware(transaction['datetime'])
    return _midnight(transaction['date'])


def _aware(dt_obj):
    # The SDK's .to_dict() gives a datetime object; tests and raw JSON give a string.
    if isinstance(dt_obj, str):
        dt_obj = parse_datetime(dt_obj)
    return timezone.make_aware(dt_obj) if timezone.is_naive(dt_obj) else dt_obj


def _midnight(date_value):
    return timezone.make_aware(datetime.combine(_as_date(date_value), datetime.min.time()))


def remove_transactions(transactions):
    count, _ = Transaction.objects.filter(transaction_id__in=transactions).delete()
    log_event(logger, "transactions_removed", level=logging.DEBUG, count=count)
