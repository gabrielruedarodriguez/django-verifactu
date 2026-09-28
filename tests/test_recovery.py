from dataclasses import replace
from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone

from django_verifactu import sending
from django_verifactu.aeat.soap import NotDelivered, OutcomeUnknown
from django_verifactu.issuing import amend, cancel
from django_verifactu.models import Record, Submission, SubmissionLine
from django_verifactu.sending import send_pending
from tests.aeat.sample import CANCELLATION, DUPLICATE, INVOICE, error
from tests.conftest import registered
from tests.shop.models import Sale

pytestmark = pytest.mark.django_db
REAL_NOW = timezone.now
STORED_WITH_ERRORS = error(3000, "Registro de facturación duplicado.") + """
    <tikR:RegistroDuplicado>
      <tik:IdPeticionRegistroDuplicado>20260924100005</tik:IdPeticionRegistroDuplicado>
      <tik:EstadoRegistroDuplicado>AceptadaConErrores</tik:EstadoRegistroDuplicado>
      <tik:CodigoErrorRegistro>2001</tik:CodigoErrorRegistro>
      <tik:DescripcionErrorRegistro>NIF no censado</tik:DescripcionErrorRegistro>
    </tikR:RegistroDuplicado>"""


def later(monkeypatch, seconds):
    moment = REAL_NOW() + timedelta(seconds=seconds)
    monkeypatch.setattr(timezone, "now", lambda: moment)


def statuses():
    return [(r.status, r.error_code) for r in Record.objects.order_by("position")]


def lost_then_answered(aeat, monkeypatch, answers):
    aeat.failure = OutcomeUnknown("lost")
    send_pending()
    aeat.failure, aeat.answers = None, answers
    later(monkeypatch, 61)
    return send_pending()


def test_a_submission_stuck_in_sending_is_recovered_and_resent(aeat, monkeypatch):
    [record] = registered("A-1")
    [stuck] = Submission._writes.bulk_create(
        [
            Submission(
                installation=record.installation,
                in_flight="T:89890001K",
                created_at=timezone.now(),
            )
        ]
    )
    SubmissionLine._writes.bulk_create([SubmissionLine(submission=stuck, record=record)])
    assert send_pending() == []
    later(monkeypatch, 11 * 60)
    [submission] = send_pending()
    stuck.refresh_from_db()
    assert (stuck.outcome, stuck.in_flight) == ("unknown", None)
    assert submission.incident
    assert statuses() == [("accepted", None)]


def test_records_without_an_answer_are_resent_declaring_an_incident(aeat, monkeypatch):
    registered("A-1")
    aeat.failure = NotDelivered("down")
    send_pending()
    registered("A-2")
    aeat.failure = None
    later(monkeypatch, 61)
    send_pending()
    later(monkeypatch, 122)
    send_pending()
    assert aeat.calls == [["A-1"], ["A-1"], ["A-2"]]
    assert aeat.incidents == [False, True, False]


def test_a_duplicate_after_a_lost_answer_is_the_record_itself(aeat, monkeypatch):
    registered("A-1", "A-2")
    answers = {"A-1": ("Incorrecto", DUPLICATE), "A-2": ("Incorrecto", STORED_WITH_ERRORS)}
    lost_then_answered(aeat, monkeypatch, answers)
    assert statuses() == [("accepted", None), ("accepted_with_errors", 2001)]
    assert Record.objects.get(invoice_number="A-2").needs_amendment


def test_a_duplicate_on_a_first_delivery_is_someone_else_s_record(aeat):
    aeat.answers = {"A-1": ("Incorrecto", DUPLICATE)}
    registered("A-1")
    send_pending()
    assert statuses() == [("rejected", 3000)]


def test_a_duplicate_proves_a_lost_cancellation_only_if_it_left_the_invoice_cancelled(
    aeat, monkeypatch
):
    with transaction.atomic():
        for number in ("A-1", "A-2"):
            cancel(Sale.objects.create(number=number), replace(CANCELLATION, invoice_number=number))
    cancelled = DUPLICATE.replace("Correcta", "Anulada")
    answers = {"A-1": ("Incorrecto", DUPLICATE), "A-2": ("Incorrecto", cancelled)}
    lost_then_answered(aeat, monkeypatch, answers)
    assert statuses() == [("rejected", 3000), ("accepted", None)]


def test_a_duplicate_never_proves_a_lost_amendment(aeat, monkeypatch):
    with transaction.atomic():
        amend(Sale.objects.create(number="A-1"), replace(INVOICE, invoice_number="A-1"))
    lost_then_answered(aeat, monkeypatch, {"A-1": ("Incorrecto", DUPLICATE)})
    assert statuses() == [("rejected", 3000)]


def test_a_late_answer_is_kept_even_after_the_submission_was_recovered(aeat, monkeypatch):
    def slow(element, **kwargs):
        later(monkeypatch, 11 * 60)
        send_pending()
        return aeat(element)

    monkeypatch.setattr(sending, "post", slow)
    registered("A-1")
    [submission] = send_pending()
    submission.refresh_from_db()
    assert (submission.outcome, submission.csv) == ("answered", "A-TEST-CSV")
    assert statuses() == [("accepted", None)]
