from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction
from django.utils import timezone

from django_verifactu import sending
from django_verifactu.aeat.records import build_registration_record
from django_verifactu.aeat.soap import NotDelivered, OutcomeUnknown
from django_verifactu.issuing import register
from django_verifactu.models import Record
from django_verifactu.sending import send_pending
from tests.aeat.live import CERTIFICATE, credentials, now, requires_aeat, software, submit
from tests.conftest import invoice_of
from tests.shop.models import Sale

pytestmark = [requires_aeat, pytest.mark.django_db]
REAL_NOW = timezone.now


def register_one(company, prefix):
    number = f"{prefix}-{now():%Y%m%d%H%M%S}"
    issue_date = timezone.localtime(timezone.now(), ZoneInfo("Europe/Madrid")).date()
    invoice = replace(invoice_of(company, number), issue_date=issue_date)
    with transaction.atomic():
        return register(Sale.objects.create(number=number), invoice)


def failing_once(monkeypatch, failure, deliver):
    real = sending.post

    def post(element, **kwargs):
        monkeypatch.setattr(sending, "post", real)
        if deliver:
            real(element, **kwargs)
        raise failure

    monkeypatch.setattr(sending, "post", post)


def later(monkeypatch, seconds):
    moment = REAL_NOW() + timedelta(seconds=seconds)
    monkeypatch.setattr(timezone, "now", lambda: moment)


def test_a_lost_answer_is_resent_with_an_incident_and_adopted(company, monkeypatch):
    register_one(company, "LOSTANSWER")
    failing_once(monkeypatch, OutcomeUnknown("answer dropped"), deliver=True)
    [lost] = send_pending()
    later(monkeypatch, 61)
    [resent] = send_pending()

    assert (lost.outcome, resent.outcome, resent.incident) == ("unknown", "answered", True)
    line = resent.lines.get()
    assert (line.status, line.error_code, line.duplicate_status) == ("Incorrecto", 3000, "Correcta")
    assert Record.objects.get().status == "accepted"


def test_an_old_record_declared_as_an_incident_gets_no_2004(company, monkeypatch):
    later(monkeypatch, -5 * 60)
    register_one(company, "OLD")
    failing_once(monkeypatch, NotDelivered("network down"), deliver=False)
    send_pending()
    monkeypatch.setattr(timezone, "now", REAL_NOW)
    [submission] = send_pending()

    assert submission.incident
    assert (Record.objects.get().status, Record.objects.get().error_code) == ("accepted", None)


def test_an_invoice_registered_elsewhere_is_rejected_as_a_duplicate(company):
    record = register_one(company, "ELSEWHERE")
    invoice = invoice_of(company, record.invoice_number)
    installation = software(company, f"ELSEWHERE-{now():%Y%m%d%H%M%S}")
    element = build_registration_record(
        invoice=invoice, software=installation, previous=None, generated_at=now()
    )
    submit(company, [element])

    send_pending()

    assert (Record.objects.get().status, Record.objects.get().error_code) == ("rejected", 3000)


def test_a_taxpayer_the_certificate_cannot_act_for_is_a_fault(company, settings):
    _, password = credentials()
    other = {"name": "Agencia Tributaria", "certificate": CERTIFICATE, "password": password}
    settings.VERIFACTU = {
        **settings.VERIFACTU,
        "TAXPAYERS": {**settings.VERIFACTU["TAXPAYERS"], "Q2826000H": other},
    }
    number = f"OTHER-{now():%Y%m%d%H%M%S}"
    invoice = replace(
        invoice_of(company, number), issuer_tax_id="Q2826000H", issuer_name="Agencia Tributaria"
    )
    with transaction.atomic():
        register(Sale.objects.create(number=number), invoice)

    [submission] = send_pending()

    assert (submission.outcome, submission.error_code) == ("fault", 4112)
    assert Record.objects.get().status == "pending"
