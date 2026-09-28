from dataclasses import replace
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import transaction

from django_verifactu.aeat.codes import IdType
from django_verifactu.aeat.domain import ForeignId, Party
from django_verifactu.issuing import register
from django_verifactu.models import Record
from django_verifactu.sending import send_pending
from tests.aeat.live import now, requires_aeat
from tests.conftest import invoice_of
from tests.shop.models import Sale

pytestmark = [requires_aeat, pytest.mark.django_db]


def test_pending_records_are_sent_and_answered_by_the_aeat(company):
    moment = now()
    owner = Party(company.name, tax_id=company.tax_id)
    unregistered = Party("Cliente", foreign_id=ForeignId(IdType.NOT_REGISTERED, "12345678Z", "ES"))
    outside_vies = Party("Kunde", foreign_id=ForeignId(IdType.VAT_NUMBER, "DE123456789"))
    with transaction.atomic():
        for index, recipients in enumerate([(owner,), (unregistered,), (outside_vies,)]):
            number = f"SEND-{moment:%Y%m%d%H%M%S}-{index}"
            invoice = replace(invoice_of(company, number), recipients=recipients)
            register(Sale.objects.create(number=number), invoice)

    [submission] = send_pending()

    assert submission.outcome == "answered" and submission.csv
    assert submission.wait_seconds == 60
    statuses = [(r.status, r.error_code) for r in Record.objects.order_by("position")]
    assert statuses == [("accepted", None), ("accepted_with_errors", 2001), ("rejected", 1239)]
    assert send_pending() == []


def test_one_pass_of_the_command_reaches_the_aeat(company):
    number = f"CMD-{now():%Y%m%d%H%M%S}"
    with transaction.atomic():
        register(Sale.objects.create(number=number), invoice_of(company, number))
    out = StringIO()
    call_command("verifactu_send", stdout=out)
    assert out.getvalue() == f"{company.tax_id}: answered, 1 records\n"
    assert Record.objects.get().status == "accepted"
