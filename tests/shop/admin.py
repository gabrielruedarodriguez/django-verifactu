from django.contrib import admin

from django_verifactu.admin import RecordInline
from tests.shop.models import Sale


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    inlines = [RecordInline]
    save_as = True
