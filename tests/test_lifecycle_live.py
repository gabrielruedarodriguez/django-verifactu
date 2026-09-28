from dataclasses import replace
from decimal import Decimal

import pytest

from django_verifactu.aeat.codes import IdType
from django_verifactu.aeat.domain import Cancellation, ForeignId, Party, TaxLine
from django_verifactu.aeat.records import build_registration_record
from django_verifactu.issuing import amend, cancel, register
from django_verifactu.qr import qr_url
from tests.aeat.live import now, requires_aeat, software, submit, validation_result
from tests.conftest import alta, anulacion, flags, invoice_of
from tests.shop.models import Sale

pytestmark = [requires_aeat, pytest.mark.django_db]
NOT_IN_VIES = (Party("Kunde GmbH", foreign_id=ForeignId(IdType.VAT_NUMBER, "DE123456789")),)
UNKNOWN_PERSON = (
    Party("Cliente", foreign_id=ForeignId(IdType.NOT_REGISTERED, "12345678Z", "ES")),
)


def sale(company, prefix):
    number = f"{prefix}-{now():%Y%m%d%H%M%S}"
    return Sale.objects.create(number=number), invoice_of(company, number)


def cancellation(invoice):
    return Cancellation(invoice.issuer_tax_id, invoice.invoice_number, invoice.issue_date)


def outcomes(obj):
    return [(r.status, r.error_code) for r in obj.verifactu_records.order_by("position")]


def registered_elsewhere(company, invoice):
    installation = software(company, f"ELSEWHERE-{now():%Y%m%d%H%M%S}")
    element = build_registration_record(
        invoice=invoice, software=installation, previous=None, generated_at=now()
    )
    submit(company, [element])


def test_a_rejected_invoice_is_registered_again(company, send):
    obj, invoice = sale(company, "REJECTED")
    register(obj, replace(invoice, recipients=NOT_IN_VIES))
    send()
    assert flags(register(obj, invoice)) == alta(Subsanacion="S", RechazoPrevio="X")
    send()
    assert outcomes(obj) == [("rejected", 1239), ("accepted", None)]


def test_an_invoice_accepted_with_errors_is_amended(company, send):
    obj, invoice = sale(company, "WITHERRORS")
    register(obj, replace(invoice, recipients=UNKNOWN_PERSON))
    send()
    assert flags(amend(obj, invoice)) == alta(Subsanacion="S")
    send()
    assert outcomes(obj) == [("accepted_with_errors", 2001), ("accepted", None)]


def test_a_rejected_amendment_is_amended_again(company, send):
    obj, invoice = sale(company, "AMENDAGAIN")
    register(obj, invoice)
    amend(obj, replace(invoice, recipients=NOT_IN_VIES))
    send()
    assert flags(amend(obj, invoice)) == alta(Subsanacion="S", RechazoPrevio="S")
    send()
    assert outcomes(obj) == [("accepted", None), ("rejected", 1239), ("accepted", None)]


def test_a_cancelled_invoice_is_reactivated_by_an_amendment(company, send):
    obj, invoice = sale(company, "REACTIVATED")
    register(obj, invoice)
    assert flags(cancel(obj, cancellation(invoice))) == anulacion()
    send()
    amend(obj, invoice)
    send()
    assert outcomes(obj) == [("accepted", None)] * 3


def test_a_rejected_cancellation_is_cancelled_again(company, send):
    obj, invoice = sale(company, "CANCELAGAIN")
    registered_elsewhere(company, invoice)
    assert flags(cancel(obj, cancellation(invoice))) == anulacion(SinRegistroPrevio="S")
    send()
    assert flags(cancel(obj, cancellation(invoice))) == anulacion(RechazoPrevio="S")
    send()
    assert outcomes(obj) == [("rejected", 3000), ("accepted", None)]


def test_an_unknown_invoice_is_cancelled_without_previous_record(company, send):
    obj, invoice = sale(company, "NORECORD")
    cancel(obj, cancellation(invoice))
    send()
    assert flags(amend(obj, invoice)) == alta(Subsanacion="S")
    send()
    assert outcomes(obj) == [("accepted", None), ("accepted", None)]


def test_a_cancellation_that_missed_its_invoice_is_retried(company, send):
    obj, invoice = sale(company, "MISSED")
    register(obj, replace(invoice, recipients=NOT_IN_VIES))
    cancel(obj, cancellation(invoice))
    send()
    expected = anulacion(SinRegistroPrevio="S", RechazoPrevio="S")
    assert flags(cancel(obj, cancellation(invoice))) == expected
    send()
    assert outcomes(obj) == [("rejected", 1239), ("rejected", 3002), ("accepted", None)]


def test_the_printed_qr_follows_the_amendments(company, send):
    obj, invoice = sale(company, "QR")
    register(obj, invoice)
    printed = qr_url(obj)
    send()
    assert validation_result(printed) == "00"
    doubled = TaxLine(rate=Decimal(21), base=Decimal(200), tax=Decimal(42))
    amend(obj, replace(invoice, lines=(doubled,)))
    send()
    assert (validation_result(printed), validation_result(qr_url(obj))) == ("01", "00")


def test_an_invoice_registered_elsewhere_is_amended_and_cancelled(company, send):
    obj, invoice = sale(company, "AMENDELSEWHERE")
    registered_elsewhere(company, invoice)
    assert flags(amend(obj, invoice)) == alta(Subsanacion="S", RechazoPrevio="X")
    send()
    assert flags(amend(obj, invoice)) == alta(Subsanacion="S", RechazoPrevio="S")
    cancel(obj, cancellation(invoice))
    send()
    assert outcomes(obj) == [("rejected", 3000), ("accepted", None), ("accepted", None)]
