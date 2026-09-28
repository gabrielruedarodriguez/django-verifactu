from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from django_verifactu.aeat.codes import (
    CorrectionType,
    IdType,
    InvoiceType,
    IssuedBy,
    PreviousRejection,
)
from django_verifactu.aeat.domain import (
    CorrectedAmounts,
    ForeignId,
    InvoiceId,
    Party,
    PreviousRecord,
    TaxLine,
)
from django_verifactu.aeat.records import build_registration_record
from django_verifactu.aeat.submission import build_submission
from django_verifactu.aeat.validation import validate_chain, validate_invoice
from django_verifactu.aeat.violations import ValidationError
from tests.aeat.sample import (
    GENERATED_AT,
    INVOICE,
    SOFTWARE,
    sample_cancellation,
    sample_registration,
)

TODAY = date(2026, 9, 24)


def codes(invoice, today=TODAY):
    return [violation.code for violation in validate_invoice(invoice, today)]


def line(rate, base, tax):
    return TaxLine(rate=Decimal(rate), base=Decimal(base), tax=Decimal(tax))


def test_sample_invoice_is_valid():
    assert codes(INVOICE) == []


@pytest.mark.parametrize("number", ["A<1", 'A"1', "A'1", "A>1", "A=1"])
def test_invoice_number_forbidden_characters(number):
    assert codes(replace(INVOICE, invoice_number=number)) == [1287]


@pytest.mark.parametrize("number", ["Añ1", "A\t1"])
def test_invoice_number_printable_ascii_only(number):
    assert codes(replace(INVOICE, invoice_number=number)) == [1130]


@pytest.mark.parametrize("number", ["", "A" * 61, " A-1", "A-1 ", " "])
def test_invoice_number_length_and_surrounding_spaces(number):
    assert codes(replace(INVOICE, invoice_number=number)) == [1104]


def test_inner_spaces_are_allowed():
    assert codes(replace(INVOICE, invoice_number="A 1")) == []


def test_issue_date_cannot_be_in_the_future():
    assert codes(replace(INVOICE, issue_date=date(2026, 9, 25))) == [1112]


def test_issue_date_not_before_2024():
    assert codes(replace(INVOICE, issue_date=date(2023, 12, 31))) == [1152]
    assert codes(replace(INVOICE, issue_date=date(2024, 1, 1))) == []


@pytest.mark.parametrize(
    ("rate", "issue_date", "expected"),
    [
        ("3", date(2026, 9, 24), [1124]),
        ("5", date(2026, 9, 24), [1194]),
        ("2", date(2026, 9, 24), [1235]),
        ("7.5", date(2026, 9, 24), [1236]),
        ("7.5", date(2024, 11, 15), []),
        ("2", date(2024, 11, 15), []),
    ],
)
def test_vat_rates(rate, issue_date, expected):
    base = Decimal(100)
    tax = base * Decimal(rate) / 100
    invoice = replace(INVOICE, issue_date=issue_date, lines=(line(rate, base, tax),))
    assert codes(invoice) == expected


def test_tax_must_match_base_times_rate_within_ten_euros():
    assert codes(replace(INVOICE, lines=(line("21", "100", "31.00"),))) == []
    assert codes(replace(INVOICE, lines=(line("21", "100", "31.01"),))) == [1142]


def test_tax_and_base_share_the_sign():
    assert codes(replace(INVOICE, lines=(line("21", "-10", "2.10"),))) == [1143]


def test_all_violations_are_reported_together():
    invoice = replace(INVOICE, invoice_number="A<1", issue_date=date(2026, 9, 25))
    assert codes(invoice) == [1287, 1112]


def test_invalid_invoice_cannot_become_a_record():
    with pytest.raises(ValidationError) as error:
        build_registration_record(
            invoice=replace(INVOICE, invoice_number="A<1"),
            software=SOFTWARE,
            previous=None,
            generated_at=GENERATED_AT,
        )
    assert [violation.code for violation in error.value.violations] == [1287]


def test_submission_issuer_must_be_the_taxpayer():
    with pytest.raises(ValidationError) as error:
        build_submission(
            taxpayer_tax_id="12345678Z", taxpayer_name="Otro SL", records=[sample_registration()]
        )
    assert [violation.code for violation in error.value.violations] == [1108]


def with_recipient(**identification):
    return replace(INVOICE, recipients=(Party(name="Cliente", **identification),))


def test_invoice_needs_a_recipient():
    assert codes(replace(INVOICE, recipients=())) == [1189]


def test_at_most_1000_recipients():
    assert codes(replace(INVOICE, recipients=INVOICE.recipients * 1001)) == [4113]


def test_recipient_needs_exactly_one_identification():
    passport = ForeignId(IdType.PASSPORT, "AB123456", "FR")
    assert codes(with_recipient()) == [4102]
    assert codes(with_recipient(tax_id="89890002E", foreign_id=passport)) == [4102]


def test_nifs_must_be_well_formed():
    assert codes(with_recipient(tax_id="89890002A")) == [1239]
    assert codes(replace(INVOICE, issuer_tax_id="89890001A")) == [1123]


@pytest.mark.parametrize(
    ("foreign_id", "expected"),
    [
        (ForeignId(IdType.PASSPORT, "AB123456", "FR"), []),
        (ForeignId(IdType.VAT_NUMBER, "DE123456789"), []),
        (ForeignId(IdType.PASSPORT, "AB123456"), [1111]),
        (ForeignId(IdType.VAT_NUMBER, "DE123456789", "FR"), [1122]),
        (ForeignId(IdType.VAT_NUMBER, "DE12345"), [1239]),
        (ForeignId(IdType.VAT_NUMBER, "GB123456789"), [1255]),
        (ForeignId(IdType.OFFICIAL_ID, "123", "ES"), [1126]),
        (ForeignId(IdType.NOT_REGISTERED, "12345678Z", "FR"), [1126]),
        (ForeignId(IdType.NOT_REGISTERED, "12345678Z", "ES"), []),
        (ForeignId(IdType.NOT_REGISTERED, "B12345674", "ES"), [1239]),
    ],
)
def test_foreign_recipient_rules(foreign_id, expected):
    assert codes(with_recipient(foreign_id=foreign_id)) == expected


def test_northern_ireland_vat_number_before_brexit():
    invoice = with_recipient(foreign_id=ForeignId(IdType.VAT_NUMBER, "XI123456789"))
    assert codes(replace(invoice, operation_date=date(2020, 12, 1))) == [1254]


@pytest.mark.parametrize(
    ("operation_date", "expected"),
    [
        (date(2026, 9, 1), []),
        (date(2005, 9, 24), [1134]),
        (date(2026, 10, 1), [1173, 1146]),
        (date(2028, 1, 1), [1125, 1173, 1146]),
    ],
)
def test_operation_date(operation_date, expected):
    assert codes(replace(INVOICE, operation_date=operation_date)) == expected


def test_vat_rate_window_uses_the_operation_date():
    invoice = replace(
        INVOICE, operation_date=date(2024, 11, 15), lines=(line("2", "100", "2"),)
    )
    assert codes(invoice) == []


def test_external_reference_length():
    assert codes(replace(INVOICE, external_reference="x" * 60)) == []
    assert codes(replace(INVOICE, external_reference="x" * 61)) == [1253]


def test_description_is_required():
    assert codes(replace(INVOICE, description=" ")) == [1100]


def test_submission_taxpayer_nif_must_be_well_formed():
    with pytest.raises(ValidationError) as error:
        build_submission(
            taxpayer_tax_id="89890001A", taxpayer_name="Emisor", records=[sample_registration()]
        )
    assert [violation.code for violation in error.value.violations] == [4116, 1108]


def test_representative_needs_a_valid_nif():
    with pytest.raises(ValidationError) as error:
        build_submission(
            taxpayer_tax_id=INVOICE.issuer_tax_id,
            taxpayer_name=INVOICE.issuer_name,
            records=[sample_registration()],
            representative=Party("Asesoria", tax_id="12345678A"),
        )
    assert [violation.code for violation in error.value.violations] == [4123]


def test_cancellation_issuer_must_be_the_taxpayer():
    with pytest.raises(ValidationError) as error:
        build_submission(
            taxpayer_tax_id="12345678Z", taxpayer_name="Otro", records=[sample_cancellation()]
        )
    assert [violation.code for violation in error.value.violations] == [1108]


SIMPLIFIED = (InvoiceType.F2, InvoiceType.R5)
ORIGINAL = InvoiceId("89890001K", "A-2026/000", date(2026, 9, 1))
PASSPORT = ForeignId(IdType.PASSPORT, "AB123456", "FR")


def of_type(invoice_type, **changes):
    corrective = invoice_type.value.startswith("R")
    shape = {
        "invoice_type": invoice_type,
        "recipients": () if invoice_type in SIMPLIFIED else INVOICE.recipients,
        "correction_type": CorrectionType.DIFFERENCES if corrective else None,
    }
    return replace(INVOICE, **(shape | changes))


@pytest.mark.parametrize("invoice_type", list(InvoiceType))
def test_every_invoice_type_has_a_valid_shape(invoice_type):
    assert codes(of_type(invoice_type)) == []


def test_correction_type_goes_with_corrective_invoices_only():
    assert codes(of_type(InvoiceType.R1, correction_type=None)) == [1114]
    assert codes(of_type(InvoiceType.F1, correction_type=CorrectionType.DIFFERENCES)) == [1115]


def test_referenced_invoices_depend_on_the_type():
    assert codes(of_type(InvoiceType.F1, corrected_invoices=(ORIGINAL,))) == [1117]
    assert codes(of_type(InvoiceType.R1, corrected_invoices=(ORIGINAL,))) == []
    assert codes(of_type(InvoiceType.F1, replaced_invoices=(ORIGINAL,))) == [1116]
    assert codes(of_type(InvoiceType.F3, replaced_invoices=(ORIGINAL,))) == []


def test_corrected_amounts_go_with_substitution_only():
    amounts = CorrectedAmounts(base=Decimal("100"), tax=Decimal("21"))
    substitution = of_type(InvoiceType.R1, correction_type=CorrectionType.SUBSTITUTION)
    assert codes(substitution) == [1118]
    assert codes(replace(substitution, corrected_amounts=amounts)) == []
    assert codes(of_type(InvoiceType.R1, corrected_amounts=amounts)) == [1119]


def test_simplified_invoices_have_no_recipients():
    assert codes(of_type(InvoiceType.F2, recipients=INVOICE.recipients)) == [1190]
    assert codes(of_type(InvoiceType.R5, recipients=INVOICE.recipients)) == [1190]


def test_simplified_invoice_limit():
    assert codes(of_type(InvoiceType.F2, lines=(line("21", "2487.60", "522.40"),))) == []
    assert codes(of_type(InvoiceType.F2, lines=(line("21", "2487.61", "522.40"),))) == [1150]
    lifted = of_type(
        InvoiceType.F2, lines=(line("21", "5000", "1050"),), without_recipient_art_61d=True
    )
    assert codes(lifted) == []


def test_invoice_flags_depend_on_the_type():
    assert codes(of_type(InvoiceType.F2, simplified_art_72_73=True)) == [1183]
    assert codes(of_type(InvoiceType.F1, without_recipient_art_61d=True)) == [1185]
    assert codes(of_type(InvoiceType.F1, coupon=True)) == [1157]
    assert codes(of_type(InvoiceType.R1, coupon=True)) == []


def test_r2_and_r3_accept_any_foreign_identification():
    passport = (Party("Cliente", foreign_id=PASSPORT),)
    assert codes(of_type(InvoiceType.R3, recipients=passport)) == []
    assert codes(of_type(InvoiceType.R2, recipients=passport)) == []


def test_tax_checks_do_not_apply_to_differences_r2_and_r3():
    off = (line("21", "100", "40"),)
    substitution = {
        "correction_type": CorrectionType.SUBSTITUTION,
        "corrected_amounts": CorrectedAmounts(Decimal(0), Decimal(0)),
    }
    assert codes(of_type(InvoiceType.R1, lines=off)) == []
    assert codes(of_type(InvoiceType.R2, lines=off, **substitution)) == []
    assert codes(of_type(InvoiceType.R3, lines=off, **substitution)) == []
    assert codes(of_type(InvoiceType.R1, lines=off, **substitution)) == [1142]


THIRD_PARTY = Party("Gestoria", tax_id="12345678Z")


def test_third_party_goes_with_issued_by_t():
    assert codes(replace(INVOICE, issued_by=IssuedBy.THIRD_PARTY, third_party=THIRD_PARTY)) == []
    assert codes(replace(INVOICE, third_party=THIRD_PARTY)) == [1155]
    assert codes(replace(INVOICE, issued_by=IssuedBy.RECIPIENT, third_party=THIRD_PARTY)) == [1159]
    assert codes(replace(INVOICE, issued_by=IssuedBy.THIRD_PARTY)) == [1158]
    assert codes(replace(INVOICE, issued_by=IssuedBy.RECIPIENT)) == []


def test_third_party_identification():
    def by(third_party):
        return codes(replace(INVOICE, issued_by=IssuedBy.THIRD_PARTY, third_party=third_party))

    assert by(Party("Emisor", tax_id=INVOICE.issuer_tax_id)) == [1188]
    assert by(Party("Gestoria", tax_id="12345678A")) == [1178]
    def foreign(id_type, number, country=None):
        return by(Party("Gestoria", foreign_id=ForeignId(id_type, number, country)))

    assert foreign(IdType.NOT_REGISTERED, "12345678Z", "ES") == [1211]
    assert foreign(IdType.OFFICIAL_ID, "X1", "ES") == [1126]
    assert foreign(IdType.VAT_NUMBER, "IE6388047V") == []


def test_billing_agreement_lifts_the_simplified_limit():
    over = of_type(InvoiceType.F2, lines=(line("21", "5000", "1050"),))
    assert codes(over) == [1150]
    assert codes(replace(over, billing_agreement="AC-2026-1")) == []


@pytest.mark.parametrize(
    ("amendment", "previous_rejection", "expected"),
    [
        (True, None, []),
        (True, PreviousRejection.NO, []),
        (True, PreviousRejection.YES, []),
        (True, PreviousRejection.NOT_AT_AEAT, []),
        (False, PreviousRejection.NO, []),
        (False, PreviousRejection.NOT_AT_AEAT, [1153]),
        (False, PreviousRejection.YES, [1161]),
    ],
)
def test_previous_rejection_needs_an_amendment(amendment, previous_rejection, expected):
    invoice = replace(INVOICE, amendment=amendment, previous_rejection=previous_rejection)
    assert codes(invoice) == expected


PREVIOUS = PreviousRecord(
    issuer_tax_id=INVOICE.issuer_tax_id,
    invoice_number="A-2026/000",
    issue_date=date(2026, 9, 23),
    fingerprint="3C464DAF61ACB827C65FDA19F352A4E3BDC2C640E9E9FC4CC058073F38F12F60",
)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({}, []),
        ({"fingerprint": PREVIOUS.fingerprint.lower()}, [2003]),
        ({"fingerprint": "G" * 64}, [2003]),
        ({"fingerprint": PREVIOUS.fingerprint[:63]}, [2002]),
        ({"issuer_tax_id": "89890001A"}, [1123]),
        ({"issuer_tax_id": "Q2826000H"}, []),
    ],
)
def test_previous_record(change, expected):
    violations = validate_chain(replace(PREVIOUS, **change))
    assert [violation.code for violation in violations] == expected


def test_first_record_has_no_chain_to_check():
    assert validate_chain(None) == []


def test_invalid_previous_record_cannot_be_chained():
    with pytest.raises(ValidationError):
        sample_registration(replace(PREVIOUS, fingerprint=PREVIOUS.fingerprint.lower()))
    with pytest.raises(ValidationError):
        sample_cancellation(replace(PREVIOUS, fingerprint=PREVIOUS.fingerprint.lower()))
