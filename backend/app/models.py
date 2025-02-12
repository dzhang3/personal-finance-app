from django.db import models

# Create your models here.
class User(models.Model):
    user_id = models.CharField(max_length=255)
    email = models.CharField(max_length=255)
    password = models.CharField(max_length=255)

class Login(models.Model):
    user_id = models.CharField(max_length=255)
    access_token = models.CharField(max_length=255)
    # item_id = models.CharField(max_length=255)
    cursor = models.CharField(max_length=255) # for transactions


class Account(models.Model):
    account_id = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255)
    account_name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=255)
    account_subtype = models.CharField(max_length=255)
    account_balance = models.FloatField()
    account_currency = models.CharField(max_length=255)

class Transaction(models.Model):
    transaction_id = models.CharField(max_length=255)
    account_id = models.CharField(max_length=255)
    amount = models.FloatField()
    currency = models.CharField(max_length=255)
    date = models.DateField()
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    transaction_type = models.CharField(max_length=255)
