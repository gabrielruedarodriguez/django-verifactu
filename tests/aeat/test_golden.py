from datetime import date
from pathlib import Path

from django_verifactu.aeat.domain import PreviousRecord
from django_verifactu.aeat.soap import wrap_in_envelope
from django_verifactu.aeat.submission import build_submission
from tests.aeat.sample import (
    INVOICE,
    sample_cancellation,
    sample_registration,
)

GOLDEN = Path(__file__).parent / "fixtures" / "golden_envelope.xml"


def envelope() -> bytes:
    previous = PreviousRecord(
        issuer_tax_id=INVOICE.issuer_tax_id,
        invoice_number="A-2026/000",
        issue_date=date(2026, 9, 23),
        fingerprint="3C464DAF61ACB827C65FDA19F352A4E3BDC2C640E9E9FC4CC058073F38F12F60",
    )
    records = [
        sample_registration(previous),
        sample_cancellation(),
    ]
    submission = build_submission(
        taxpayer_tax_id=INVOICE.issuer_tax_id, taxpayer_name=INVOICE.issuer_name, records=records
    )
    return wrap_in_envelope(submission)


def test_generated_xml_matches_the_golden_file():
    assert envelope() == GOLDEN.read_bytes()
