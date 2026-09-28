from dataclasses import replace

import pytest
from django.db import transaction

from django_verifactu.aeat.violations import ValidationError
from django_verifactu.issuing import (
    AlreadyCancelled,
    AlreadyRegistered,
    LifecycleError,
    amend,
    cancel,
    register,
)
from django_verifactu.models import Installation, Record
from django_verifactu.sending import send_pending
from tests.aeat.sample import CANCELLATION, INVOICE
from tests.conftest import alta, anulacion, flags
from tests.shop.models import Sale

pytestmark = pytest.mark.django_db


def sale(number=INVOICE.invoice_number):
    return Sale.objects.create(number=number)


def answered(record, status, code=None):
    Record._writes.filter(pk=record.pk).update(status=status, error_code=code)


def test_an_accepted_invoice_is_amended():
    obj = sale()
    answered(register(obj, INVOICE), "accepted")
    record = amend(obj, replace(INVOICE, description="Servicios corregidos"))
    assert (record.operation, record.amendment, record.position) == ("Alta", True, 2)
    assert flags(record) == alta(Subsanacion="S")


def test_a_rejected_amendment_is_amended_again():
    obj = sale()
    answered(register(obj, INVOICE), "accepted")
    answered(amend(obj, INVOICE), "rejected", 1100)
    assert flags(amend(obj, INVOICE)) == alta(Subsanacion="S", RechazoPrevio="S")


def test_a_rejected_invoice_is_registered_again_as_missing_at_the_aeat():
    obj = sale()
    answered(register(obj, INVOICE), "rejected", 1239)
    record = register(obj, INVOICE)
    assert record.amendment
    assert flags(record) == alta(Subsanacion="S", RechazoPrevio="X")


def test_an_invoice_the_aeat_holds_is_registered_once():
    obj = sale()
    answered(register(obj, INVOICE), "rejected", 3000)
    with pytest.raises(AlreadyRegistered):
        register(obj, INVOICE)
    assert flags(amend(obj, INVOICE)) == alta(Subsanacion="S")


def test_a_registered_invoice_is_cancelled():
    obj = sale()
    register(obj, INVOICE)
    record = cancel(obj, CANCELLATION)
    assert (record.operation, record.amendment, record.position) == ("Anulacion", False, 2)
    assert (record.invoice_number, record.issue_date) == (
        INVOICE.invoice_number,
        INVOICE.issue_date,
    )
    assert flags(record) == anulacion()
    assert list(obj.verifactu_records.order_by("position").values_list("operation", flat=True)) == [
        "Alta",
        "Anulacion",
    ]


def test_an_invoice_without_records_is_cancelled_without_previous_record():
    assert flags(cancel(sale(), CANCELLATION)) == anulacion(SinRegistroPrevio="S")


def test_a_rejected_cancellation_is_cancelled_again():
    obj = sale()
    answered(register(obj, INVOICE), "accepted")
    answered(cancel(obj, CANCELLATION), "rejected", 1100)
    assert flags(cancel(obj, CANCELLATION)) == anulacion(RechazoPrevio="S")


def test_an_invoice_is_cancelled_once():
    obj = sale()
    register(obj, INVOICE)
    cancel(obj, CANCELLATION)
    with pytest.raises(AlreadyCancelled):
        cancel(obj, CANCELLATION)


def test_amending_a_cancelled_invoice_reactivates_it():
    obj = sale()
    register(obj, INVOICE)
    cancel(obj, CANCELLATION)
    assert flags(amend(obj, INVOICE)) == alta(Subsanacion="S")
    assert flags(cancel(obj, CANCELLATION)) == anulacion()


def test_each_environment_has_its_own_lifecycle(settings):
    obj = sale()
    register(obj, INVOICE)
    settings.VERIFACTU = {**settings.VERIFACTU, "PRODUCTION": True}
    assert flags(register(obj, INVOICE)) == alta()


def test_another_object_cannot_take_over_an_invoice():
    register(sale(), INVOICE)
    with pytest.raises(LifecycleError):
        amend(sale(), INVOICE)
    with pytest.raises(LifecycleError):
        cancel(sale(), CANCELLATION)


def test_an_object_keeps_its_invoice():
    obj = sale()
    register(obj, INVOICE)
    with pytest.raises(LifecycleError):
        register(obj, replace(INVOICE, invoice_number="A-2026/002"))


def test_rejected_records_bind_no_invoice_to_an_object():
    first = sale()
    answered(register(first, INVOICE), "rejected", 1100)
    assert register(sale(), INVOICE).amendment
    assert register(first, replace(INVOICE, invoice_number="A-2026/002")).position == 3


@pytest.mark.parametrize(
    "changes", [{"without_previous_record": True}, {"previous_rejection": True}]
)
def test_cancellation_flags_are_decided_by_the_library(changes):
    with pytest.raises(ValueError):
        cancel(sale(), replace(CANCELLATION, **changes))


def test_amendment_flags_are_decided_by_the_library():
    with pytest.raises(ValueError):
        amend(sale(), replace(INVOICE, amendment=True))


@pytest.mark.parametrize("changes", [{"invoice_number": ""}, {"issuer_tax_id": "89890001A"}])
def test_invalid_cancellations_write_nothing(changes):
    with pytest.raises(ValidationError):
        cancel(sale(), replace(CANCELLATION, **changes))
    assert not Record.objects.exists()
    assert not Installation.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_a_registration_and_its_cancellation_travel_together(aeat):
    with transaction.atomic():
        obj = sale()
        register(obj, INVOICE)
        cancel(obj, CANCELLATION)
    [submission] = send_pending()
    assert aeat.calls == [[INVOICE.invoice_number, INVOICE.invoice_number]]
    assert list(Record.objects.order_by("position").values_list("status", flat=True)) == [
        "accepted",
        "accepted",
    ]
    assert submission.lines.count() == 2
