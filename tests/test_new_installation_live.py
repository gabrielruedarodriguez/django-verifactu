from dataclasses import replace

import pytest

from django_verifactu.issuing import amend, new_installation, register
from django_verifactu.models import Record
from django_verifactu.verifying import verify
from tests.aeat.live import now, requires_aeat
from tests.conftest import invoice_of
from tests.shop.models import Sale

pytestmark = [requires_aeat, pytest.mark.django_db]


def registered(company, prefix):
    number = f"{prefix}-{now():%Y%m%d%H%M%S}"
    obj, invoice = Sale.objects.create(number=number), invoice_of(company, number)
    return register(obj, invoice), invoice


def test_a_restarted_chain_is_accepted_and_the_old_one_still_sent(company, send):
    old, invoice = registered(company, "GENERATION1")
    send()
    registered(company, "LEFTPENDING")
    installation = new_installation(company.tax_id)
    registered(company, "GENERATION2")
    amended = amend(old.content_object, replace(invoice, description="Servicios corregidos"))
    send()
    send()
    records = Record.objects.order_by("installation__generation", "position")
    assert [(r.installation.generation, r.status, r.error_code) for r in records] == [
        (1, "accepted", None),
        (1, "accepted", None),
        (2, "accepted", None),
        (2, "accepted", None),
    ]
    assert amended.installation == installation
    assert verify(aeat=True) == []
