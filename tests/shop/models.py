from django.db import models

from django_verifactu.models import VerifactuRecords


class Customer(models.Model):
    name = models.CharField(max_length=60)


class Sale(models.Model):
    number = models.CharField(max_length=60)
    customer = models.ForeignKey(Customer, models.CASCADE, null=True)
    verifactu_records = VerifactuRecords()


class Note(models.Model):
    text = models.CharField(max_length=60)
