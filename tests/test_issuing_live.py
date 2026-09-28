from dataclasses import replace

import pytest
from lxml import etree

from django_verifactu.aeat.codes import RecordStatus
from django_verifactu.aeat.domain import Party
from django_verifactu.issuing import register
from tests.aeat.live import now, requires_aeat, submit, taxpayer
from tests.aeat.sample import INVOICE
from tests.shop.models import Sale

pytestmark = [requires_aeat, pytest.mark.django_db]


def test_registered_records_are_accepted_by_the_aeat(settings):
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    software = {**settings.VERIFACTU["SOFTWARE"], "producer": owner}
    settings.VERIFACTU = {**settings.VERIFACTU, "SOFTWARE": software}
    records = []
    for index in range(3):
        number = f"DJ-{moment:%Y%m%d%H%M%S}-{index}"
        invoice = replace(
            INVOICE,
            issuer_tax_id=company.tax_id,
            issuer_name=company.name,
            invoice_number=number,
            issue_date=moment.date(),
            recipients=(owner,),
        )
        records.append(register(Sale.objects.create(number=number), invoice))

    result = submit(company, [etree.fromstring(record.xml) for record in records])

    assert [line.status for line in result.records] == [RecordStatus.ACCEPTED] * 3
