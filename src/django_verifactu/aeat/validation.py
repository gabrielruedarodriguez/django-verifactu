import re
from datetime import date
from decimal import Decimal

from django_verifactu.aeat.breakdown import check_breakdown, has_pending_tax
from django_verifactu.aeat.codes import (
    CorrectionType,
    GeneratedBy,
    IdType,
    InvoiceType,
    IssuedBy,
    PreviousRejection,
)
from django_verifactu.aeat.domain import (
    BillingSoftware,
    Cancellation,
    ForeignId,
    Invoice,
    Party,
    PreviousRecord,
)
from django_verifactu.aeat.identifiers import (
    is_natural_person_nif,
    is_valid_nif,
    is_valid_vat_number,
)
from django_verifactu.aeat.violations import Violation

MAX_RECIPIENTS = 1000
# Verified live: the AEAT rejects (1152) issue dates before 2024-01-01, although the
# message of 1152 mentions 28-10-2024.
EARLIEST_ISSUE_DATE = date(2024, 1, 1)
_FORBIDDEN_CHARACTERS = set("\"'<>=")
_CORRECTIVE = {InvoiceType.R1, InvoiceType.R2, InvoiceType.R3, InvoiceType.R4, InvoiceType.R5}
_SIMPLIFIED = {InvoiceType.F2, InvoiceType.R5}
# 3000 euros plus the 10 euros of tolerance the AEAT admits.
_F2_LIMIT = Decimal("3010.00")
_BREXIT = date(2021, 1, 1)
_GB_PREFIX_END = date(2021, 1, 31)
_HEX = set("0123456789ABCDEF")
_SYSTEM_ID = re.compile("[A-Z0-9]{2}")


def validate_invoice(invoice: Invoice, today: date) -> list[Violation]:
    tax_date = invoice.operation_date or invoice.issue_date
    violations = _check_invoice_number(invoice.invoice_number)
    if not is_valid_nif(invoice.issuer_tax_id):
        violations.append(Violation(1123, "issuer_tax_id is not a valid NIF"))
    if not invoice.description.strip():
        violations.append(Violation(1100, "description is required"))
    violations += _check_external_reference(invoice.external_reference)
    violations += _check_previous_rejection(invoice)
    violations += _check_dates(invoice, today)
    violations += _check_invoice_type(invoice)
    violations += _check_recipients(invoice, tax_date)
    violations += _check_third_party(invoice, tax_date)
    violations += check_breakdown(invoice, tax_date)
    return violations


def _check_invoice_number(number: str) -> list[Violation]:
    violations = []
    if not 1 <= len(number) <= 60:
        violations.append(Violation(1104, "invoice_number must have 1 to 60 characters"))
    # Verified live: the AEAT stores the number trimmed but ValidarQR does not trim it, so
    # the QR code of such an invoice would never be found.
    elif number != number.strip(" "):
        violations.append(Violation(1104, "invoice_number cannot start or end with spaces"))
    if any(not 32 <= ord(char) <= 126 for char in number):
        violations.append(Violation(1130, "invoice_number allows printable ASCII only"))
    if any(char in _FORBIDDEN_CHARACTERS for char in number):
        violations.append(Violation(1287, "invoice_number cannot contain \" ' < > ="))
    return violations


def _check_external_reference(reference: str | None) -> list[Violation]:
    if reference is not None and len(reference) > 60:
        return [Violation(1253, "external_reference has at most 60 characters")]
    return []


def _check_previous_rejection(invoice: Invoice) -> list[Violation]:
    if invoice.amendment:
        return []
    if invoice.previous_rejection is PreviousRejection.NOT_AT_AEAT:
        return [Violation(1153, "previous_rejection NOT_AT_AEAT is only for an amendment")]
    if invoice.previous_rejection is PreviousRejection.YES:
        return [Violation(1161, "previous_rejection YES is only for an amendment")]
    return []


def _check_dates(invoice: Invoice, today: date) -> list[Violation]:
    violations = []
    if invoice.issue_date > today:
        violations.append(Violation(1112, "issue_date is in the future"))
    if invoice.issue_date < EARLIEST_ISSUE_DATE:
        violations.append(Violation(1152, f"issue_date is before {EARLIEST_ISSUE_DATE}"))
    operation_date = invoice.operation_date
    if operation_date is None:
        return violations
    if operation_date < _years_before(today, 20):
        violations.append(Violation(1134, "operation_date is more than 20 years old"))
    if operation_date.year > today.year + 1:
        violations.append(Violation(1125, "operation_date is beyond next year"))
    if has_pending_tax(invoice):
        return violations
    if operation_date > today:
        violations.append(Violation(1173, "operation_date is in the future"))
    if invoice.issue_date < operation_date:
        violations.append(Violation(1146, "issue_date is before operation_date"))
    return violations


def _check_invoice_type(invoice: Invoice) -> list[Violation]:
    kind = invoice.invoice_type
    corrective = kind in _CORRECTIVE
    substitution = invoice.correction_type is CorrectionType.SUBSTITUTION
    violations = []
    if corrective and invoice.correction_type is None:
        violations.append(Violation(1114, "R invoices need a correction_type"))
    if not corrective and invoice.correction_type is not None:
        violations.append(Violation(1115, "only R invoices have a correction_type"))
    if invoice.corrected_invoices and not corrective:
        violations.append(Violation(1117, "only R invoices list corrected_invoices"))
    if invoice.replaced_invoices and kind is not InvoiceType.F3:
        violations.append(Violation(1116, "only F3 invoices list replaced_invoices"))
    if substitution and invoice.corrected_amounts is None:
        violations.append(Violation(1118, "a substitution needs corrected_amounts"))
    if not substitution and invoice.corrected_amounts is not None:
        violations.append(Violation(1119, "corrected_amounts only go with a substitution"))
    if invoice.simplified_art_72_73 and kind in _SIMPLIFIED:
        violations.append(Violation(1183, "simplified_art_72_73 is not for F2 or R5"))
    if invoice.without_recipient_art_61d and kind not in _SIMPLIFIED:
        violations.append(Violation(1185, "without_recipient_art_61d is for F2 or R5 only"))
    if invoice.coupon and kind not in (InvoiceType.R1, InvoiceType.R5):
        violations.append(Violation(1157, "coupon is for R1 or R5 only"))
    total = sum(line.base + (line.tax or 0) for line in invoice.lines)
    lifted = invoice.without_recipient_art_61d or invoice.billing_agreement is not None
    if kind is InvoiceType.F2 and not lifted and total > _F2_LIMIT:
        violations.append(Violation(1150, "an F2 invoice cannot exceed 3000 euros"))
    return violations


def _check_recipients(invoice: Invoice, tax_date: date) -> list[Violation]:
    recipients = invoice.recipients
    if invoice.invoice_type in _SIMPLIFIED:
        return [Violation(1190, "F2 and R5 invoices have no recipients")] if recipients else []
    if not recipients:
        return [Violation(1189, "the invoice needs at least one recipient")]
    if len(recipients) > MAX_RECIPIENTS:
        return [Violation(4113, f"an invoice holds at most {MAX_RECIPIENTS} recipients")]
    violations = []
    for recipient in recipients:
        if (recipient.tax_id is None) == (recipient.foreign_id is None):
            violations.append(Violation(4102, "a recipient needs either tax_id or foreign_id"))
        elif recipient.tax_id is not None and not is_valid_nif(recipient.tax_id):
            violations.append(Violation(1239, "recipient tax_id is not a valid NIF"))
        elif recipient.foreign_id is not None:
            violations += _check_foreign_id(recipient.foreign_id, tax_date)
    # The catalogued R2/R3 identification rules (1191, 1192) are not enforced by the AEAT
    # (verified live with ids 03, 04, 05 and 06), so they are deliberately not checked.
    return violations


def _check_third_party(invoice: Invoice, tax_date: date) -> list[Violation]:
    issued_by, third_party = invoice.issued_by, invoice.third_party
    if third_party is not None and issued_by is None:
        return [Violation(1155, "third_party needs issued_by")]
    if third_party is not None and issued_by is IssuedBy.RECIPIENT:
        return [Violation(1159, "third_party is only for invoices issued by a third party")]
    missing_third_party = issued_by is IssuedBy.THIRD_PARTY and third_party is None
    if missing_third_party or (issued_by is IssuedBy.RECIPIENT and not invoice.recipients):
        return [Violation(1158, "issued_by needs its third_party or recipients block")]
    if third_party is None:
        return []
    if (third_party.tax_id is None) == (third_party.foreign_id is None):
        return [Violation(4102, "third_party needs either tax_id or foreign_id")]
    if third_party.tax_id is not None:
        if not is_valid_nif(third_party.tax_id):
            return [Violation(1178, "third_party tax_id is not a valid NIF")]
        if third_party.tax_id == invoice.issuer_tax_id:
            return [Violation(1188, "the third party cannot be the issuer")]
        return []
    foreign_id = third_party.foreign_id
    if foreign_id.id_type is IdType.NOT_REGISTERED:
        return [Violation(1211, "a third party cannot use a not registered (07) id")]
    return _check_foreign_id(foreign_id, tax_date, block_code=1178)


def validate_cancellation(cancellation: Cancellation) -> list[Violation]:
    violations = []
    if not is_valid_nif(cancellation.issuer_tax_id):
        violations.append(Violation(1123, "issuer_tax_id is not a valid NIF"))
    violations += _check_invoice_number(cancellation.invoice_number)
    violations += _check_external_reference(cancellation.external_reference)
    return violations + _check_generator(
        cancellation.issuer_tax_id, cancellation.generated_by, cancellation.generator
    )


def validate_chain(previous: PreviousRecord | None) -> list[Violation]:
    if previous is None:
        return []
    violations = []
    if not is_valid_nif(previous.issuer_tax_id):
        violations.append(Violation(1123, "previous issuer_tax_id is not a valid NIF"))
    if len(previous.fingerprint) != 64:
        violations.append(Violation(2002, "previous fingerprint must have 64 characters"))
    elif not set(previous.fingerprint) <= _HEX:
        violations.append(Violation(2003, "previous fingerprint must be uppercase hexadecimal"))
    return violations


def validate_software(software: BillingSoftware, tax_date: date) -> list[Violation]:
    violations = _check_producer(software.producer, tax_date)
    # Empty or longer values break the XSD, which the AEAT answers with 1100 instead.
    if 0 < len(software.system_id) <= 2 and not _SYSTEM_ID.fullmatch(software.system_id):
        violations.append(Violation(1177, "system_id must be two uppercase letters or digits"))
    return violations


def _check_producer(producer: Party, tax_date: date) -> list[Violation]:
    if (producer.tax_id is None) == (producer.foreign_id is None):
        return [Violation(4102, "the producer needs either tax_id or foreign_id")]
    if producer.tax_id is not None:
        if is_valid_nif(producer.tax_id):
            return []
        return [Violation(4109, "the producer tax_id is not a valid NIF")]
    foreign_id = producer.foreign_id
    id_type, number, country = foreign_id.id_type, foreign_id.number, foreign_id.country
    if id_type is IdType.VAT_NUMBER:
        return _check_vat_number(number, country, tax_date, block_code=1103)
    if id_type is IdType.NOT_REGISTERED:
        return [Violation(1221, "a producer cannot use a not registered (07) id")]
    if country is None:
        return [Violation(1111, "country is required unless the id is a VAT number")]
    if country == "ES" and id_type is not IdType.PASSPORT:
        return [Violation(1232, "with country ES the producer id must be a passport (03)")]
    return []


def _check_generator(
    issuer_tax_id: str, generated_by: GeneratedBy | None, generator: Party | None
) -> list[Violation]:
    if (generated_by is None) != (generator is None):
        return [Violation(1224, "generated_by and generator go together")]
    if generator is None:
        return []
    if (generator.tax_id is None) == (generator.foreign_id is None):
        return [Violation(1228, "generator needs either tax_id or foreign_id")]
    if generated_by is GeneratedBy.ISSUER and generator.tax_id is None:
        return [Violation(1227, "a cancellation generated by the issuer needs a NIF")]
    if generator.tax_id is not None:
        if not is_valid_nif(generator.tax_id) or generator.tax_id == issuer_tax_id:
            return [Violation(1259, "the generator NIF must be valid and not the issuer's")]
        return []
    id_type, country = generator.foreign_id.id_type, generator.foreign_id.country
    if generated_by is GeneratedBy.THIRD_PARTY and id_type is IdType.NOT_REGISTERED:
        return [Violation(1229, "a third party generator cannot use a not registered (07) id")]
    spanish_recipient = generated_by is GeneratedBy.RECIPIENT and country == "ES"
    if spanish_recipient and id_type not in (IdType.PASSPORT, IdType.NOT_REGISTERED):
        return [Violation(1234, "a Spanish recipient generator needs a passport (03) or 07")]
    spanish_third_party = generated_by is GeneratedBy.THIRD_PARTY and country == "ES"
    if spanish_third_party and id_type is not IdType.PASSPORT:
        return [Violation(1232, "a Spanish third party generator needs a passport (03)")]
    return []


def _check_foreign_id(
    foreign_id: ForeignId, tax_date: date, block_code: int = 1239
) -> list[Violation]:
    id_type, number, country = foreign_id.id_type, foreign_id.number, foreign_id.country
    if id_type is IdType.VAT_NUMBER:
        return _check_vat_number(number, country, tax_date, block_code)
    if country is None:
        return [Violation(1111, "country is required unless the id is a VAT number")]
    if country == "ES" and id_type not in (IdType.PASSPORT, IdType.NOT_REGISTERED):
        return [Violation(1126, "with country ES the id must be a passport (03) or 07")]
    if id_type is IdType.NOT_REGISTERED and country != "ES":
        return [Violation(1126, "a not registered (07) id requires country ES")]
    if id_type is IdType.NOT_REGISTERED and not is_natural_person_nif(number):
        return [Violation(block_code, "a not registered (07) id must be a natural person NIF")]
    return []


def _check_vat_number(
    number: str, country: str | None, tax_date: date, block_code: int
) -> list[Violation]:
    if country is not None and country != number[:2]:
        return [Violation(1122, "country does not match the VAT number prefix")]
    if not is_valid_vat_number(number):
        return [Violation(block_code, "the VAT number does not follow its EU country structure")]
    if number.startswith("XI") and tax_date < _BREXIT:
        return [Violation(1254, "XI VAT numbers only exist since 2021-01-01")]
    if number.startswith("GB") and tax_date > _GB_PREFIX_END:
        return [Violation(1255, "GB VAT numbers are not accepted since 2021-02-01")]
    return []


def _years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)
