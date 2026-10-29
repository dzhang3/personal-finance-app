from django.db import models
from django.contrib.auth.models import AbstractUser, Group, Permission

# Create your models here.
class User(AbstractUser):
    name = models.CharField(max_length=255, blank=True)
    
    # Fix reverse accessor clashes
    groups = models.ManyToManyField(
        Group,
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to.',
        related_name='app_user_set',
        related_query_name='app_user'
    )
    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name='app_user_set',
        related_query_name='app_user'
    )
    
    def save(self, *args, **kwargs):
        if not self.name and self.username:
            self.name = self.username
        super().save(*args, **kwargs)

    def __str__(self):
        return f"User(id={self.id}, username={self.username})"

class Account(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    account_id = models.CharField(max_length=255)
    plaid_item = models.ForeignKey('PlaidItem', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=50, choices=[('bank', 'Bank'), ('credit_card', 'Credit Card'), ('loan', 'Loan'), ('investment', 'Investment')])
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    institution = models.CharField(max_length=255, blank=True, null=True)

class Transaction(models.Model):
    # Decision 014: Plaid's transaction_id is the idempotency key.
    transaction_id = models.CharField(max_length=255, unique=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    # When the purchase happened: Plaid's authorized datetime/date, falling back to posted.
    datetime = models.DateTimeField()
    # Decision 022: Plaid's posted `date`, stored as-is. /transactions/get filters
    # on this field, so reconciliation windows must use it too. Null only for rows
    # written before this field existed; the first reconcile or sync fills them.
    posted_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    # Plaid's personal_finance_category.primary, e.g. GENERAL_MERCHANDISE (19 chars).
    transaction_type = models.CharField(max_length=50)
    transaction_type_is_custom = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    merchant_id = models.CharField(max_length=255, blank=True, null=True)
    merchant_name = models.CharField(max_length=255, blank=True, null=True)
    payment_channel = models.CharField(max_length=255, blank=True, null=True)


class SavingsGoal(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    target_amount = models.DecimalField(max_digits=12, decimal_places=2)
    current_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    deadline = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Paycheck(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    breakdown = models.JSONField(default=dict)  # Example: {"401k": 200, "ESPP": 100, "Taxes": 500}
    created_at = models.DateTimeField(auto_now_add=True)


class MonthlySpending(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    month = models.IntegerField()
    year = models.IntegerField()
    amount_saved = models.DecimalField(max_digits=12, decimal_places=2)
    amount_spent = models.DecimalField(max_digits=12, decimal_places=2)
    amount_income = models.DecimalField(max_digits=12, decimal_places=2)
    amount_spent_food = models.DecimalField(max_digits=12, decimal_places=2)
    amount_spent_utilities = models.DecimalField(max_digits=12, decimal_places=2)
    amount_spent_transportation = models.DecimalField(max_digits=12, decimal_places=2)
    amount_spent_misc = models.DecimalField(max_digits=12, decimal_places=2)


class BudgetTarget(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='budget_targets')
    # Empty category represents the optional overall monthly target.
    category = models.CharField(max_length=50, blank=True, default='')
    monthly_limit = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'category'], name='unique_budget_target_per_user_category'),
        ]


class PlaidItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    item_id = models.CharField(max_length=255, unique=True)
    access_token = models.CharField(max_length=255)
    institution_name = models.CharField(max_length=255, blank=True, null=True)
    cursor = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class SyncJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        IN_PROGRESS = 'in_progress', 'In Progress'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    class Step(models.TextChoices):
        FETCH_TRANSACTIONS = 'fetch_transactions', 'Fetch Transactions'
        UPDATE_DB = 'update_db', 'Update Database'

    class Kind(models.TextChoices):
        SYNC = 'sync', 'Sync'
        # Decision 020: reconciliation runs through the same queue, so the
        # one-active-job constraint keeps it from racing a sync on the same Item.
        RECONCILE = 'reconcile', 'Reconcile'

    plaid_item = models.ForeignKey(PlaidItem, on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SYNC)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    error_code = models.CharField(max_length=100, blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    attempt_number = models.IntegerField(default=1)
    # step moved to SyncAttempt (decision 011): it describes one attempt, not the whole job.
    # For sync jobs: rows added/modified/removed. For reconcile jobs: rows
    # inserted/updated/deleted by repairs (see ReconcileRepair).
    added_count = models.IntegerField(default=0)
    modified_count = models.IntegerField(default=0)
    removed_count = models.IntegerField(default=0)
    # Decision 012: a queued job is not claimable before this time. Null means "now".
    run_after = models.DateTimeField(null=True, blank=True)
    # Decision 030: while in_progress, the claiming worker owns the job until this
    # time and must renew it as it works. Once it passes, another worker may claim
    # the job as a new attempt. attempt_number doubles as the fencing token.
    lease_expires_at = models.DateTimeField(null=True, blank=True)

    ACTIVE_STATUSES = (Status.QUEUED, Status.IN_PROGRESS)

    class Meta:
        constraints = [
            # Decision 008: at most one queued or in-progress job per Item, enforced by Postgres.
            models.UniqueConstraint(
                fields=['plaid_item'],
                condition=models.Q(status__in=['queued', 'in_progress']),
                name='one_active_job_per_item',
            ),
        ]


class SyncAttempt(models.Model):
    """One execution of a SyncJob (decision 011).

    The attempt row owns per-attempt details (timing, step, error). The SyncJob
    row owns the overall lifecycle and final outcome.
    """
    class Outcome(models.TextChoices):
        COMPLETED = 'completed', 'Completed'
        RETRY_SCHEDULED = 'retry_scheduled', 'Failed, retry scheduled'
        FAILED = 'failed', 'Failed permanently'
        # The worker stopped renewing (died or froze) and another worker took over.
        LEASE_EXPIRED = 'lease_expired', 'Abandoned, lease expired'

    job = models.ForeignKey(SyncJob, on_delete=models.CASCADE, related_name='attempts')
    attempt_number = models.IntegerField()
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    # Null while the attempt is still running (or if the worker died mid-attempt).
    outcome = models.CharField(max_length=20, choices=Outcome.choices, null=True, blank=True)
    step = models.CharField(max_length=50, choices=SyncJob.Step.choices, null=True, blank=True)
    error_code = models.CharField(max_length=100, blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['job', 'attempt_number'], name='unique_attempt_number_per_job'),
        ]


class ReconcileRepair(models.Model):
    """One change a reconcile job made to the Transaction table (decision 019).

    Audit trail for auto-repair: if a bad run deletes or overwrites real data,
    this records exactly what it did and what the row looked like before.
    """
    class Action(models.TextChoices):
        INSERTED = 'inserted', 'Inserted missing transaction'
        UPDATED = 'updated', 'Updated mismatched transaction'
        DELETED = 'deleted', 'Deleted extra transaction'

    job = models.ForeignKey(SyncJob, on_delete=models.CASCADE, related_name='repairs')
    transaction_id = models.CharField(max_length=255)
    action = models.CharField(max_length=20, choices=Action.choices)
    # Snapshots of the compared fields. before is null for inserts, after is null for deletes.
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)