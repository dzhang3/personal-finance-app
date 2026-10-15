"""Reconciliation: compare stored transactions against Plaid for a trailing window
and repair drift (decisions 018-021).

Flow of one reconcile job (run by run_job, so it gets the same retries as a sync):
    1. fetch_plaid_window   Plaid's view, from /transactions/get (a different
                            endpoint from the sync path, decision 018)
    2. local_window         our view of the same window              (Daniel)
    3. compute_diff         missing / extra / mismatched             (Daniel)
    4. apply_repairs        fix the table and record every change (decision 019)
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

from decimal import Decimal
from app import db_methods as db
from app.models import ReconcileRepair, SyncJob, Transaction

RECONCILE_WINDOW_DAYS = 30  # decision 021
PLAID_PAGE_SIZE = 500  # /transactions/get maximum


class IncompleteFetchError(Exception):
    """Plaid's total_transactions didn't match what we received.

    Raised instead of reconciling against a partial list, because a partial
    Plaid view would make real local rows look "extra" and get them deleted.
    Not on the retry allowlist: it fails the job loudly.
    """


def reconcile_item(plaid_item, job, attempt, window_days=RECONCILE_WINDOW_DAYS):
    """Reconcile one Item. Called by run_job for jobs of kind RECONCILE. Raises on failure."""
    end_date = timezone.localdate()
    start_date = end_date - timedelta(days=window_days)

    attempt.step = SyncJob.Step.FETCH_TRANSACTIONS
    attempt.save(update_fields=['step'])
    plaid_txns, plaid_accounts = fetch_plaid_window(plaid_item, start_date, end_date)

    attempt.step = SyncJob.Step.UPDATE_DB
    attempt.save(update_fields=['step'])
    # Accounts first, so repairs never hit the upsert's missing-account skip.
    db.update_accounts(plaid_item.user, plaid_item, plaid_accounts)

    local_txns = local_window(plaid_item, start_date, end_date)
    missing, extra, mismatched = compute_diff(plaid_txns, local_txns)
    apply_repairs(job, plaid_item.user, missing, extra, mismatched)


def fetch_plaid_window(plaid_item, start_date, end_date):
    """All of Plaid's transactions for this Item in [start_date, end_date], plus its accounts.

    /transactions/get pages by offset. If a transaction arrives mid-fetch the
    offsets shift, so the result is checked against total_transactions.
    """
    from app.views import client  # lazy: app.views imports app.jobs

    transactions = []
    while True:
        request = TransactionsGetRequest(
            access_token=plaid_item.access_token,
            start_date=start_date,
            end_date=end_date,
            options=TransactionsGetRequestOptions(
                count=PLAID_PAGE_SIZE,
                offset=len(transactions),
                include_personal_finance_category=True,
            ),
        )
        response = client.transactions_get(request).to_dict()
        page = response['transactions']
        transactions.extend(page)
        total = response['total_transactions']
        if not page or len(transactions) >= total:
            break

    # Count unique IDs, not list length: if a new transaction shifts the offsets
    # mid-fetch, one row is returned twice and another is skipped, and the list
    # length can still equal total.
    unique_ids = {t['transaction_id'] for t in transactions}
    if len(unique_ids) != total or len(transactions) != total:
        raise IncompleteFetchError(
            f"Plaid reported {total} transactions but returned "
            f"{len(transactions)} ({len(unique_ids)} unique)"
        )
    return transactions, response['accounts']


# --- Daniel writes these two ------------------------------------------------

def local_window(plaid_item, start_date, end_date):
    """Our stored transactions for this Item whose date falls in [start_date, end_date].

    - Only this Item's transactions (Transaction -> Account -> PlaidItem).
    - Plaid filters by posted date, so filter on posted_date (decision 022).
    - Return something compute_diff can iterate (a QuerySet is fine).
    """
    return Transaction.objects.filter(
        account__plaid_item=plaid_item,
        posted_date__gte=start_date,
        posted_date__lte=end_date,
    ).select_related('account')


def compute_diff(plaid_txns, local_txns):
    """Compare Plaid's transactions against ours. Pure function: no DB writes.

    plaid_txns: list of dicts from /transactions/get (.to_dict() shape;
                'amount' is a float, 'date' is a datetime.date).
    local_txns: iterable of Transaction model instances.

    Returns (missing, extra, mismatched):
      missing:    Plaid dicts with no local row          -> will be inserted
      extra:      Transaction instances Plaid doesn't have -> will be deleted
      mismatched: (plaid_dict, Transaction) pairs whose compared fields differ
                  -> local row will be overwritten with Plaid's data

    You decide which fields count as a mismatch. Watch the types: Decimal vs
    float for amount, date vs datetime for date.
    """
    missing = []
    extra = []
    mismatched = []

    # Build a mapping of local transactions by transaction_id for quick lookup
    local_txn_map = {txn.transaction_id: txn for txn in local_txns}
    for plaid_txn in plaid_txns:    
        local_txn = local_txn_map.get(plaid_txn['transaction_id'])
        if local_txn is None:
            missing.append(plaid_txn)
        else:
            # Compare fields to determine if there's a mismatch
            if (
                Decimal(str(plaid_txn['amount'])).quantize(Decimal('0.01')) != local_txn.amount or
                local_txn.posted_date != plaid_txn['date'] or
                local_txn.merchant_name != plaid_txn.get('merchant_name')
            ):
                mismatched.append((plaid_txn, local_txn))

    # Identify extra transactions that are in local but not in Plaid
    plaid_txn_ids = {txn['transaction_id'] for txn in plaid_txns}
    for local_txn in local_txns:
        if local_txn.transaction_id not in plaid_txn_ids:
            extra.append(local_txn)
    return (missing, extra, mismatched)

    


# --- Repairs -----------------------------------------------------------------

def apply_repairs(job, user, missing, extra, mismatched):
    """Apply the diff and write one ReconcileRepair row per change, all in one transaction.

    Either every repair and its audit row commit, or none do.
    """
    repairs = []
    for plaid_txn in missing:
        repairs.append(ReconcileRepair(
            job=job, transaction_id=plaid_txn['transaction_id'],
            action=ReconcileRepair.Action.INSERTED,
            after=_plaid_snapshot(plaid_txn),
        ))
    for plaid_txn, local_txn in mismatched:
        repairs.append(ReconcileRepair(
            job=job, transaction_id=local_txn.transaction_id,
            action=ReconcileRepair.Action.UPDATED,
            before=_local_snapshot(local_txn), after=_plaid_snapshot(plaid_txn),
        ))
    for local_txn in extra:
        repairs.append(ReconcileRepair(
            job=job, transaction_id=local_txn.transaction_id,
            action=ReconcileRepair.Action.DELETED,
            before=_local_snapshot(local_txn),
        ))

    with transaction.atomic():
        accounts = {}
        if missing:
            db.upsert_transactions(list(missing), accounts, user)
        if mismatched:
            db.upsert_transactions([p for p, _ in mismatched], accounts, user)
        if extra:
            Transaction.objects.filter(pk__in=[t.pk for t in extra]).delete()
        ReconcileRepair.objects.bulk_create(repairs)

    # run_job saves these with the job's outcome.
    job.added_count = len(missing)
    job.modified_count = len(mismatched)
    job.removed_count = len(extra)


def _plaid_snapshot(plaid_txn):
    return {
        'amount': str(plaid_txn.get('amount')),
        'date': str(plaid_txn.get('date')),
        'merchant_name': plaid_txn.get('merchant_name'),
        'pending': plaid_txn.get('pending'),
        'account_id': plaid_txn.get('account_id'),
    }


def _local_snapshot(local_txn):
    return {
        'amount': str(local_txn.amount),
        'datetime': local_txn.datetime.isoformat(),
        'merchant_name': local_txn.merchant_name,
        'account_id': local_txn.account.account_id,
    }
