import os
from dataclasses import replace

from django_verifactu.aeat.codes import SubmissionStatus
from django_verifactu.aeat.domain import Party
from django_verifactu.aeat.records import build_registration_record
from tests.aeat.live import now, requires_aeat, software, submit, taxpayer
from tests.aeat.sample import INVOICE

pytestmark = requires_aeat


def test_submission_reaches_the_aeat_test_environment():
    owner = taxpayer()
    moment = now()
    recipient = Party(
        name=os.environ.get("VERIFACTU_TEST_RECIPIENT_NAME", INVOICE.recipients[0].name),
        tax_id=os.environ.get("VERIFACTU_TEST_RECIPIENT_TAX_ID", INVOICE.recipients[0].tax_id),
    )
    invoice = replace(
        INVOICE,
        issuer_tax_id=owner.tax_id,
        issuer_name=owner.name,
        invoice_number=f"TEST-{moment:%Y%m%d%H%M%S}",
        issue_date=moment.date(),
        recipients=(recipient,),
    )
    record = build_registration_record(
        invoice=invoice, software=software(owner), previous=None, generated_at=moment
    )

    result = submit(owner, [record])

    print(result)
    assert result.status in SubmissionStatus
    assert len(result.records) == 1
