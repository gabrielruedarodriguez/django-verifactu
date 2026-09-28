
import pytest
from django.contrib.admin.utils import NestedObjects
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import ProtectedError

from django_verifactu.issuing import register
from django_verifactu.models import Record
from tests.aeat.sample import INVOICE
from tests.shop.models import Customer, Sale

pytestmark = pytest.mark.django_db


def registered_sale(customer=None):
    sale = Sale.objects.create(number="A-2026/001", customer=customer)
    register(sale, INVOICE)
    return sale


def test_objects_with_records_cannot_be_deleted():
    sale = registered_sale()
    with pytest.raises(ProtectedError):
        sale.delete()
    with pytest.raises(ProtectedError):
        Sale.objects.all().delete()
    assert Record.objects.count() == 1


def test_cascades_stop_at_objects_with_records():
    customer = Customer.objects.create(name="Cliente")
    registered_sale(customer)
    with pytest.raises(ProtectedError):
        customer.delete()
    assert Sale.objects.count() == 1


def test_the_content_type_of_registered_objects_cannot_be_deleted():
    registered_sale()
    with pytest.raises(ProtectedError):
        ContentType.objects.get_for_model(Sale).delete()


def test_objects_without_records_are_deleted_normally():
    Sale.objects.create(number="A-1").delete()
    assert not Sale.objects.exists()


def test_the_transaction_stays_usable_after_a_refused_delete():
    sale = registered_sale()
    with transaction.atomic():
        with pytest.raises(ProtectedError):
            sale.delete()
        assert Sale.objects.count() == 1


def test_the_admin_reports_the_records_as_protected():
    sale = registered_sale()
    collector = NestedObjects(using="default")
    collector.collect([sale])
    assert list(collector.protected) == list(sale.verifactu_records.all())
