from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from django_verifactu.aeat.domain import Cancellation, TaxLine
from django_verifactu.issuing import amend, cancel, register
from django_verifactu.models import Record, SubmissionLine
from django_verifactu.verifying import verify
from tests.aeat.live import now, requires_aeat
from tests.conftest import invoice_of
from tests.shop.models import Sale
from tests.test_lifecycle_live import NOT_IN_VIES

pytestmark = [requires_aeat, pytest.mark.django_db]


def registered(company, prefix):
    number = f"{prefix}-{now():%Y%m%d%H%M%S}"
    obj, invoice = Sale.objects.create(number=number), invoice_of(company, number)
    register(obj, invoice)
    return obj, invoice


def test_the_aeat_holds_what_the_database_says(company, send):
    registered(company, "VERIFIED")
    amended = registered(company, "VERIFYAMEND")
    obj, invoice = registered(company, "VERIFYCANCEL")
    send()
    doubled = TaxLine(rate=Decimal(21), base=Decimal(200), tax=Decimal(42))
    amend(amended[0], replace(amended[1], lines=(doubled,)))
    cancel(obj, Cancellation(invoice.issuer_tax_id, invoice.invoice_number, invoice.issue_date))
    send()
    assert set(Record.objects.values_list("status", flat=True)) == {"accepted"}
    assert verify(aeat=True) == []


def test_the_aeat_files_invoices_under_their_issue_month(company, send):
    number = f"LASTMONTH-{now():%Y%m%d%H%M%S}"
    last_month = now().date().replace(day=1) - timedelta(days=1)
    invoice = replace(invoice_of(company, number), issue_date=last_month)
    register(Sale.objects.create(number=number), invoice)
    send()
    assert Record.objects.get().status == "accepted"
    assert verify(aeat=True) == []


def test_an_accepted_record_the_aeat_does_not_hold_is_reported(company, send):
    number = f"NOTHELD-{now():%Y%m%d%H%M%S}"
    invoice = replace(invoice_of(company, number), recipients=NOT_IN_VIES)
    register(Sale.objects.create(number=number), invoice)
    send()
    Record._writes.update(status="accepted", error_code=None)
    [problem] = verify(aeat=True)
    assert number in problem and "does not hold #1" in problem


def test_a_database_restored_from_a_backup_is_detected(company, send):
    registered(company, "KEPT")
    registered(company, "LOST")
    send()
    lost = Record.objects.order_by("position").last()
    SubmissionLine._writes.filter(record=lost).delete()
    Record._writes.filter(pk=lost.pk).delete()
    [problem] = verify(aeat=True)
    assert lost.invoice_number in problem
    assert "the AEAT holds it from this system, but the database does not" in problem
