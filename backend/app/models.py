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

class Cursor(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    access_token = models.CharField(max_length=255)
    cursor = models.CharField(max_length=255)

class Account(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    account_id = models.CharField(max_length=255)
    access_token = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=50, choices=[('bank', 'Bank'), ('credit_card', 'Credit Card'), ('loan', 'Loan'), ('investment', 'Investment')])
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    institution = models.CharField(max_length=255, blank=True, null=True)

class Transaction(models.Model):
    transaction_id = models.CharField(max_length=255)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    datetime = models.DateTimeField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    transaction_type = models.CharField(max_length=10,)
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

