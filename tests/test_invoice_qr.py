from dataclasses import replace
from decimal import Decimal

import pytest
from django.template import Context, Template

from django_verifactu.aeat.domain import TaxLine
from django_verifactu.aeat.qr import LABEL, LEGEND
from django_verifactu.issuing import NotRegistered, amend, cancel, register
from django_verifactu.models import Record
from django_verifactu.qr import qr_url
from tests.aeat.sample import CANCELLATION, INVOICE
from tests.shop.models import Sale

pytestmark = pytest.mark.django_db
TEST_URL = "https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR"
QUERY = "?nif=89890001K&numserie=A-2026%2F001&fecha=24-09-2026&importe="
DOUBLED = replace(INVOICE, lines=(TaxLine(rate=Decimal(21), base=Decimal(200), tax=Decimal(42)),))


def sale():
    return Sale.objects.create(number=INVOICE.invoice_number)


def answered(record, status, code=None):
    Record._writes.filter(pk=record.pk).update(status=status, error_code=code)


def test_the_qr_carries_the_registered_invoice():
    obj = sale()
    register(obj, INVOICE)
    assert qr_url(obj) == f"{TEST_URL}{QUERY}121.00"


def test_the_qr_follows_the_latest_amendment():
    obj = sale()
    register(obj, INVOICE)
    amend(obj, DOUBLED)
    assert qr_url(obj).endswith("&importe=242.00")


def test_a_rejected_amendment_keeps_the_previous_qr():
    obj = sale()
    register(obj, INVOICE)
    answered(amend(obj, DOUBLED), "rejected", 1239)
    assert qr_url(obj).endswith("&importe=121.00")


def test_a_cancelled_invoice_keeps_its_qr():
    obj = sale()
    register(obj, INVOICE)
    cancel(obj, CANCELLATION)
    assert qr_url(obj).endswith("&importe=121.00")


def test_only_registered_objects_have_a_qr():
    obj = sale()
    with pytest.raises(NotRegistered):
        qr_url(obj)
    cancel(obj, CANCELLATION)
    with pytest.raises(NotRegistered):
        qr_url(obj)


def test_a_rejected_registration_has_no_qr():
    obj = sale()
    answered(register(obj, INVOICE), "rejected", 1239)
    with pytest.raises(NotRegistered):
        qr_url(obj)


def test_the_qr_belongs_to_the_current_environment(settings):
    obj = sale()
    register(obj, INVOICE)
    settings.VERIFACTU = {**settings.VERIFACTU, "PRODUCTION": True}
    with pytest.raises(NotRegistered):
        qr_url(obj)
    register(obj, DOUBLED)
    assert qr_url(obj) == (
        f"https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR{QUERY}242.00"
    )


def test_the_template_tag_prints_the_qr_with_the_texts_the_aeat_requires():
    obj = sale()
    register(obj, INVOICE)
    html = Template("{% load verifactu %}{% verifactu_qr obj %}").render(Context({"obj": obj}))
    assert html.index(LABEL) < html.index("<svg") < html.index(LEGEND)
    assert "&lt;" not in html


def test_the_template_tag_refuses_objects_without_a_registration():
    with pytest.raises(NotRegistered):
        Template("{% load verifactu %}{% verifactu_qr obj %}").render(Context({"obj": sale()}))
