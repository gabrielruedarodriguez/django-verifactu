import copy
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from django_verifactu.aeat import query, records, submission
from django_verifactu.aeat.codes import (
    DuplicateStatus,
    ExemptionCause,
    IdType,
    RecordStatus,
    StoredStatus,
)
from django_verifactu.aeat.domain import (
    Cancellation,
    ForeignId,
    Invoice,
    Party,
    PreviousRecord,
    Query,
)
from django_verifactu.aeat.elements import RECORDS, add, tag
from django_verifactu.aeat.qr import qr_url
from django_verifactu.aeat.soap import AeatFault
from django_verifactu.aeat.validation import (
    validate_cancellation,
    validate_chain,
    validate_invoice,
    validate_software,
)
from django_verifactu.aeat.violations import ValidationError
from tests.aeat.cases import (
    business_cases,
    cancellation_cases,
    chain_cases,
    foreign,
    header_cases,
    lifecycle_cases,
    query_cases,
    software_cases,
    vat,
)
from tests.aeat.live import (
    ask,
    now,
    requires_aeat,
    send,
    software,
    submit,
    taxpayer,
    validation_result,
)
from tests.aeat.sample import INVOICE

pytestmark = requires_aeat


# Checks only the AEAT can make (census, VIES): the local validation accepts these.
AEAT_ONLY = {
    "EU VAT number not in VIES": (RecordStatus.REJECTED, 1239),
    "not registered in Spain": (RecordStatus.ACCEPTED_WITH_ERRORS, 2001),
    "producer NIF not in the census": (RecordStatus.REJECTED, 1110),
    "producer VAT number not in VIES": (RecordStatus.REJECTED, 1103),
}

def element(record, path: str):
    return record.find("/".join(tag(RECORDS, part) for part in path.split("/")))


def set_text(path: str, value: str):
    def mutate(record):
        element(record, path).text = value

    return mutate


def add_external_reference(text: str):
    def mutate(record):
        record.insert(2, copy.deepcopy(element(record, "IDVersion")))
        record[2].tag = tag(RECORDS, "RefExterna")
        record[2].text = text

    return mutate


def remove_recipient_nif(record):
    recipient = element(record, "Destinatarios/IDDestinatario")
    recipient.remove(element(recipient, "NIF"))


def add_recipient_passport(record):
    foreign = add(element(record, "Destinatarios/IDDestinatario"), RECORDS, "IDOtro")
    add(foreign, RECORDS, "CodigoPais", "FR")
    add(foreign, RECORDS, "IDType", IdType.PASSPORT)
    add(foreign, RECORDS, "ID", "AB123456")


def add_recipients(count: int):
    def mutate(record):
        recipients = element(record, "Destinatarios")
        for _ in range(count):
            recipients.append(copy.deepcopy(recipients[0]))

    return mutate


# XML-level cases the builder refuses: a valid record is built, then broken on purpose.
# Each case: (mutation of the XML, the same change applied to the invoice).
def schema_cases():
    return {
        "empty invoice number": (
            set_text("IDFactura/NumSerieFactura", ""),
            lambda i: replace(i, invoice_number=""),
        ),
        "invoice number over 60 characters": (
            set_text("IDFactura/NumSerieFactura", "X" * 61),
            lambda i: replace(i, invoice_number="X" * 61),
        ),
        "description over 500 characters": (
            set_text("DescripcionOperacion", "x" * 501),
            lambda i: replace(i, description="x" * 501),
        ),
        "issuer name over 120 characters": (
            set_text("NombreRazonEmisor", "x" * 121),
            lambda i: replace(i, issuer_name="x" * 121),
        ),
        "external reference over 60 characters": (
            add_external_reference("x" * 61),
            lambda i: replace(i, external_reference="x" * 61),
        ),
        "empty issuer name": (
            set_text("NombreRazonEmisor", ""),
            lambda i: replace(i, issuer_name=""),
        ),
        "blank recipient name": (
            set_text("Destinatarios/IDDestinatario/NombreRazon", " "),
            lambda i: replace(i, recipients=(replace(i.recipients[0], name=" "),)),
        ),
        "blank description": (
            set_text("DescripcionOperacion", " "),
            lambda i: replace(i, description=" "),
        ),
    }


def software_schema_cases():
    def field(element: str, value: str, **change):
        return set_text(f"SistemaInformatico/{element}", value), lambda s: replace(s, **change)

    return {
        "blank system name": field("NombreSistemaInformatico", " ", name=" "),
        "system name over 30 characters": field(
            "NombreSistemaInformatico", "x" * 31, name="x" * 31
        ),
        "empty system id": field("IdSistemaInformatico", "", system_id=""),
        "system id of 3 characters": field("IdSistemaInformatico", "ABC", system_id="ABC"),
        "empty version": field("Version", "", version=""),
        "version over 50 characters": field("Version", "1" * 51, version="1" * 51),
        "empty installation number": field("NumeroInstalacion", "", installation_number=""),
        "installation number over 100 characters": field(
            "NumeroInstalacion", "1" * 101, installation_number="1" * 101
        ),
        "blank producer name": (
            set_text("SistemaInformatico/NombreRazon", " "),
            lambda s: replace(s, producer=replace(s.producer, name=" ")),
        ),
        "producer name over 120 characters": (
            set_text("SistemaInformatico/NombreRazon", "x" * 121),
            lambda s: replace(s, producer=replace(s.producer, name="x" * 121)),
        ),
    }


def cancellation_schema_cases():
    return {
        "empty cancelled invoice number": (
            set_text("IDFactura/NumSerieFacturaAnulada", ""),
            lambda c: replace(c, invoice_number=""),
        ),
        "cancelled invoice number over 60 characters": (
            set_text("IDFactura/NumSerieFacturaAnulada", "X" * 61),
            lambda c: replace(c, invoice_number="X" * 61),
        ),
        "cancellation external reference over 60 characters": (
            add_external_reference("x" * 61),
            lambda c: replace(c, external_reference="x" * 61),
        ),
    }


def base_invoice(owner: Party, number: str, today: date) -> Invoice:
    return replace(
        INVOICE,
        issuer_tax_id=owner.tax_id,
        issuer_name=owner.name,
        invoice_number=number,
        issue_date=today,
        recipients=(owner,),
    )


def matches(name: str, local: list[int], status: RecordStatus, code: int | None) -> bool:
    if name in AEAT_ONLY:
        return (status, code) == AEAT_ONLY[name]
    if not local:
        return status is RecordStatus.ACCEPTED
    return status is not RecordStatus.ACCEPTED and code in local


def check(expected: list[tuple[str, list[int]]], lines) -> None:
    report, mismatches = [], []
    for (name, local), line in zip(expected, lines, strict=True):
        row = f"{name}: local {local or 'valid'} | AEAT {line.status.value} {line.error_code or ''}"
        report.append(row)
        if not matches(name, local, line.status, line.error_code):
            mismatches.append(f"{row} {line.error_description or ''}")
    print("\n".join(report))
    assert not mismatches, "\n".join(mismatches)


def link(operation: Invoice | Cancellation, record) -> PreviousRecord:
    return PreviousRecord(
        operation.issuer_tax_id, operation.invoice_number, operation.issue_date, record[-1].text
    )


def build(operation: Invoice | Cancellation, installation, previous, moment):
    if isinstance(operation, Invoice):
        return records.build_registration_record(
            invoice=operation, software=installation, previous=previous, generated_at=moment
        )
    return records.build_cancellation_record(
        cancellation=operation, software=installation, previous=previous, generated_at=moment
    )


def test_business_rules_match_the_aeat(monkeypatch):
    monkeypatch.setattr(records, "validate_invoice", lambda invoice, today: [])
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    installation = software(company, f"CONF-{moment:%Y%m%d%H%M%S}")
    built, expected, previous = [], [], None
    for index, (name, change) in enumerate(business_cases(moment.date(), owner).items()):
        number = f"CONF-{moment:%Y%m%d%H%M%S}-{index:02d}"
        invoice = change(base_invoice(owner, number, moment.date()))
        record = build(invoice, installation, previous, moment)
        previous = link(invoice, record)
        built.append(record)
        violations = validate_invoice(invoice, moment.date())
        expected.append((name, [violation.code for violation in violations]))

    result = submit(company, built)

    check(expected, result.records)
    lines = dict(zip([name for name, _ in expected], result.records, strict=True))
    assert lines["not registered in Spain"].needs_amendment
    assert not lines["IPSI line without regime"].needs_amendment
    assert result.presenter_tax_id == company.tax_id


def test_cancellation_rules_match_the_aeat(monkeypatch):
    monkeypatch.setattr(records, "validate_cancellation", lambda cancellation: [])
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    installation = software(company, f"CANCEL-{moment:%Y%m%d%H%M%S}")
    built, expected, previous = [], [], None
    for index, (name, change) in enumerate(cancellation_cases(owner).items()):
        invoice = base_invoice(owner, f"CANCEL-{moment:%Y%m%d%H%M%S}-{index:02d}", moment.date())
        registration = build(invoice, installation, previous, moment)
        cancellation = change(
            Cancellation(invoice.issuer_tax_id, invoice.invoice_number, invoice.issue_date)
        )
        record = build(cancellation, installation, link(invoice, registration), moment)
        previous = link(cancellation, record)
        built += [registration, record]
        violations = validate_cancellation(cancellation)
        expected.append((name, [violation.code for violation in violations]))

    result = submit(company, built)

    registrations, cancellations = result.records[0::2], result.records[1::2]
    assert all(line.status is RecordStatus.ACCEPTED for line in registrations)
    check(expected, cancellations)
    lines = dict(zip([name for name, _ in expected], cancellations, strict=True))
    assert lines["cancellation with an external reference"].external_reference == "ERP-1"


def test_lifecycle_follows_the_official_tables(monkeypatch):
    monkeypatch.setattr(records, "validate_invoice", lambda invoice, today: [])
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    installation = software(company, f"LIFE-{moment:%Y%m%d%H%M%S}")
    built, expected, previous = [], [], None
    for index, (name, steps) in enumerate(lifecycle_cases().items()):
        invoice = base_invoice(owner, f"LIFE-{moment:%Y%m%d%H%M%S}-{index:02d}", moment.date())
        for step, answer in steps:
            operation = step(invoice)
            record = build(operation, installation, previous, moment)
            previous = link(operation, record)
            built.append(record)
            expected.append((name, answer))

    result = submit(company, built)

    report, mismatches = [], []
    for (name, (status, code)), line in zip(expected, result.records, strict=True):
        row = f"{name}: expected {status.value} {code or ''} | AEAT {line.status.value} "
        row += f"{line.error_code or ''} {line.error_description or ''}"
        report.append(row)
        if (line.status, line.error_code) != (status, code):
            mismatches.append(row)
    print("\n".join(report))
    assert not mismatches, "\n".join(mismatches)


def test_chain_rules_match_the_aeat(monkeypatch):
    monkeypatch.setattr(records, "validate_chain", lambda previous: [])
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    installation = software(company, f"CHAIN-{moment:%Y%m%d%H%M%S}")
    first = base_invoice(owner, f"CHAIN-{moment:%Y%m%d%H%M%S}-00", moment.date())
    built = [build(first, installation, None, moment)]
    expected = []
    for index, (name, previous) in enumerate(chain_cases(link(first, built[0])).items(), 1):
        invoice = base_invoice(owner, f"CHAIN-{moment:%Y%m%d%H%M%S}-{index:02d}", moment.date())
        built.append(build(invoice, installation, previous, moment))
        expected.append((name, [violation.code for violation in validate_chain(previous)]))

    result = submit(company, built)

    assert result.records[0].status is RecordStatus.ACCEPTED
    check(expected, result.records[1:])


def builder_codes(operation: Invoice | Cancellation, installation, moment) -> list[int]:
    try:
        build(operation, installation, None, moment)
    except ValidationError as error:
        return [violation.code for violation in error.violations]
    return []


def outcome(send_it) -> tuple[int | None, str]:
    try:
        [line] = send_it().records
        return line.error_code, line.error_description or line.status.value
    except AeatFault as fault:
        return fault.error_code, fault.message


def test_schema_rules_match_the_aeat():
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    installation = software(company, f"SCHEMA-{moment:%Y%m%d%H%M%S}")
    built, expected, previous = [], [], None
    for index, (name, (mutate, change)) in enumerate(schema_cases().items()):
        invoice = base_invoice(owner, f"SCHEMA-{moment:%Y%m%d%H%M%S}-{index:02d}", moment.date())
        record = build(invoice, installation, previous, moment)
        previous = link(invoice, record)
        mutate(record)
        built.append(record)
        expected.append((name, builder_codes(change(invoice), installation, moment)))
    for index, (name, (mutate, change)) in enumerate(cancellation_schema_cases().items()):
        cancellation = Cancellation(
            owner.tax_id,
            f"SCHEMA-{moment:%Y%m%d%H%M%S}-C{index}",
            moment.date(),
            without_previous_record=True,
        )
        record = build(cancellation, installation, previous, moment)
        previous = link(cancellation, record)
        mutate(record)
        built.append(record)
        expected.append((name, builder_codes(change(cancellation), installation, moment)))
    for index, (name, (mutate, change)) in enumerate(software_schema_cases().items()):
        invoice = base_invoice(owner, f"SCHEMA-{moment:%Y%m%d%H%M%S}-S{index}", moment.date())
        record = build(invoice, installation, previous, moment)
        previous = link(invoice, record)
        mutate(record)
        built.append(record)
        expected.append((name, builder_codes(invoice, change(installation), moment)))

    check(expected, submit(company, built).records)


def single_record(label: str):
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    installation = software(company, f"{label}-{moment:%Y%m%d%H%M%S}")
    invoice = base_invoice(owner, f"{label}-{moment:%Y%m%d%H%M%S}", moment.date())
    record = build(invoice, installation, None, moment)
    return company, owner, installation, moment, invoice, record


def remove_qualification(record):
    detail = element(record, "Desglose/DetalleDesglose")
    detail.remove(element(detail, "CalificacionOperacion"))


def add_exemption(record):
    qualification = element(record, "Desglose/DetalleDesglose/CalificacionOperacion")
    exemption = copy.deepcopy(qualification)
    exemption.tag, exemption.text = tag(RECORDS, "OperacionExenta"), ExemptionCause.E1
    qualification.addnext(exemption)


def add_detail_lines(count: int):
    def mutate(record):
        breakdown = element(record, "Desglose")
        for _ in range(count):
            breakdown.append(copy.deepcopy(breakdown[0]))

    return mutate


def remove_detail_lines(record):
    breakdown = element(record, "Desglose")
    for detail in list(breakdown):
        breakdown.remove(detail)


def structure_cases(owner: Party):
    passport = ForeignId(IdType.PASSPORT, "AB123456", "FR")
    return {
        "recipient without identification": (
            remove_recipient_nif,
            lambda i: replace(i, recipients=(Party(owner.name),)),
        ),
        "recipient with NIF and foreign id": (
            add_recipient_passport,
            lambda i: replace(i, recipients=(replace(owner, foreign_id=passport),)),
        ),
        "line without qualification or exemption": (
            remove_qualification,
            lambda i: replace(i, lines=(replace(i.lines[0], qualification=None),)),
        ),
        "line with qualification and exemption": (
            add_exemption,
            lambda i: replace(i, lines=(replace(i.lines[0], exemption=ExemptionCause.E1),)),
        ),
        "13 breakdown lines": (add_detail_lines(12), lambda i: replace(i, lines=i.lines * 13)),
        "no breakdown lines": (remove_detail_lines, lambda i: replace(i, lines=())),
    }


# Broken XML structure can make the AEAT reject the whole submission, so each travels alone.
@pytest.mark.parametrize("name", list(structure_cases(Party("", tax_id=""))))
def test_structure_errors_match_the_aeat(name):
    company, owner, installation, moment, invoice, record = single_record("STRUCTURE")
    mutate, change = structure_cases(owner)[name]
    mutate(record)
    local = builder_codes(change(invoice), installation, moment)
    aeat_code, detail = outcome(lambda: submit(company, [record]))
    print(f"{name}: local {local} | AEAT {aeat_code} {detail}")
    assert aeat_code in local, f"{name}: local {local} | AEAT {aeat_code} {detail}"


def test_more_than_1000_recipients_is_refused_by_the_xsd_although_the_aeat_accepts_it():
    company, owner, installation, moment, invoice, record = single_record("CROWDED")
    add_recipients(1000)(record)
    crowded = replace(invoice, recipients=(owner,) * 1001)
    assert [v.code for v in validate_invoice(crowded, moment.date())] == [4113]
    aeat_code, detail = outcome(lambda: submit(company, [record]))
    assert aeat_code is None, f"the AEAT now rejects it: {aeat_code} {detail}"


@pytest.mark.parametrize("name", list(header_cases(Party("", tax_id=""), date.today())))
def test_header_rules_match_the_aeat(monkeypatch, name):
    company, owner, installation, moment, invoice, record = single_record("HEADER")
    changes = dict(header_cases(owner, moment.date())[name])
    incident = changes.pop("incident", False)
    arguments = {
        "taxpayer_tax_id": company.tax_id,
        "taxpayer_name": company.name,
        "records": [record] * changes.pop("records", 1),
    } | changes
    violations = submission.validate_submission(**arguments, today=moment.date())
    local = [violation.code for violation in violations]
    monkeypatch.setattr(submission, "validate_submission", lambda **arguments: [])
    built = submission.build_submission(**arguments, incident=incident)
    aeat_code, detail = outcome(lambda: send(built))
    print(f"{name}: local {local or 'valid'} | AEAT {aeat_code} {detail}")
    assert (aeat_code in local) if local else aeat_code is None, detail


def test_software_rules_match_the_aeat(monkeypatch):
    monkeypatch.setattr(records, "validate_software", lambda software, tax_date: [])
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    installation = software(company, f"SOFT-{moment:%Y%m%d%H%M%S}")
    built, expected, previous = [], [], None
    for index, (name, change) in enumerate(software_cases().items()):
        invoice = base_invoice(owner, f"SOFT-{moment:%Y%m%d%H%M%S}-{index:02d}", moment.date())
        system = change(installation)
        record = build(invoice, system, previous, moment)
        previous = link(invoice, record)
        built.append(record)
        violations = validate_software(system, invoice.issue_date)
        expected.append((name, [violation.code for violation in violations]))

    check(expected, submit(company, built).records)


# The AEAT flags (2004) records generated more than 240 seconds away from its clock,
# unless the submission declares a technical incident.
def test_late_records_need_the_incident_flag():
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    late = moment - timedelta(minutes=10)
    installation = software(company, f"LATE-{moment:%Y%m%d%H%M%S}")
    first = base_invoice(owner, f"LATE-{moment:%Y%m%d%H%M%S}-1", late.date())
    second = replace(first, invoice_number=f"LATE-{moment:%Y%m%d%H%M%S}-2")
    record = build(first, installation, None, late)

    [line] = submit(company, [record]).records
    assert (line.status, line.error_code) == (RecordStatus.ACCEPTED_WITH_ERRORS, 2004)
    assert not line.needs_amendment

    chained = build(second, installation, link(first, record), late)
    declared = submission.build_submission(
        taxpayer_tax_id=company.tax_id,
        taxpayer_name=company.name,
        records=[chained],
        incident=True,
    )
    [line] = send(declared).records
    assert line.status is RecordStatus.ACCEPTED, line.error_description


# Query checks only the AEAT can make (census, powers), answered with these codes.
QUERY_AEAT_ONLY = {
    "taxpayer NIF of another taxpayer": 4112,
    "taxpayer NIF not in the census": 4104,
    "counterparty NIF not in the census": 4107,
}
# The XSD limits it to 60 characters although the AEAT just finds nothing.
QUERY_STRICTER = {"external reference over 60 characters"}


def query_codes(wanted: Query) -> list[int]:
    try:
        query.build_query(wanted)
    except ValidationError as error:
        return [violation.code for violation in error.violations]
    return []


@pytest.mark.parametrize("name", list(query_cases(Party("", tax_id=""), date.today(), None)))
def test_query_rules_match_the_aeat(monkeypatch, name):
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    changes = query_cases(owner, moment.date(), software(company))[name]
    wanted = replace(Query(company.tax_id, company.name, moment.year, moment.month), **changes)
    local = query_codes(wanted)
    monkeypatch.setattr(query, "validate_query", lambda wanted: [])
    monkeypatch.setattr(query, "schema_violations", lambda element, name: [])
    try:
        ask(query.build_query(wanted))
        aeat_code, detail = None, "answered"
    except AeatFault as fault:
        aeat_code, detail = fault.error_code, fault.message
    print(f"{name}: local {local or 'valid'} | AEAT {aeat_code} {detail}")
    if name in QUERY_AEAT_ONLY:
        assert (local, aeat_code) == ([], QUERY_AEAT_ONLY[name]), detail
    elif name in QUERY_STRICTER:
        assert local and aeat_code is None, detail
    else:
        assert (aeat_code in local) if local else aeat_code is None, detail


def test_query_finds_the_records_just_submitted():
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    installation = software(company, f"FIND-{moment:%Y%m%d%H%M%S}")
    built, invoices, previous = [], [], None
    for index in range(3):
        number = f"FIND-{moment:%Y%m%d%H%M%S}-{index}"
        invoice = replace(base_invoice(owner, number, moment.date()), external_reference=number)
        record = build(invoice, installation, previous, moment)
        previous = link(invoice, record)
        built.append(record)
        invoices.append(invoice)
    result = submit(company, built)
    day = Query(company.tax_id, company.name, moment.year, moment.month, issue_date=moment.date())

    wanted = replace(day, invoice_number=invoices[0].invoice_number, show_software=True)
    [stored] = ask(query.build_query(wanted)).records
    assert stored.software == installation
    assert stored.status is StoredStatus.ACCEPTED
    assert stored.fingerprint == built[0][-1].text
    assert (stored.presenter_tax_id, stored.presented_at) == (company.tax_id, result.presented_at)

    wanted = replace(day, external_reference=invoices[1].external_reference)
    [referenced] = ask(query.build_query(wanted)).records
    assert referenced.invoice.invoice_number == invoices[1].invoice_number

    wanted = replace(day, as_recipient=True, invoice_number=invoices[2].invoice_number)
    [received] = ask(query.build_query(wanted)).records
    assert (received.fingerprint, received.total_amount) == (None, Decimal(121))

    page = ask(query.build_query(day))
    following = ask(query.build_query(replace(day, after=page.records[0].invoice)))
    assert following.records[0].invoice == page.records[1].invoice


def test_qr_of_a_registered_invoice_is_found_by_the_aeat():
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    installation = software(company, f"QR-{moment:%Y%m%d%H%M%S}")
    kept = base_invoice(owner, f"QR-{moment:%Y%m%d%H%M%S}-1", moment.date())
    cancelled = replace(kept, invoice_number=f"QR-{moment:%Y%m%d%H%M%S}-2")
    first = build(kept, installation, None, moment)
    second = build(cancelled, installation, link(kept, first), moment)
    cancellation = Cancellation(cancelled.issuer_tax_id, cancelled.invoice_number, moment.date())
    third = build(cancellation, installation, link(cancelled, second), moment)
    submit(company, [first, second, third])

    assert validation_result(qr_url(first, production=False)) == "00"
    assert validation_result(qr_url(second, production=False)) == "01"


def test_resending_a_submission_whose_answer_was_lost_is_safe(monkeypatch):
    monkeypatch.setattr(records, "validate_invoice", lambda invoice, today: [])
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    installation = software(company, f"LOST-{moment:%Y%m%d%H%M%S}")
    kept = base_invoice(owner, f"LOST-{moment:%Y%m%d%H%M%S}-1", moment.date())
    refused = replace(
        kept, invoice_number=f"LOST-{moment:%Y%m%d%H%M%S}-2", lines=vat("3", "100", "3")
    )
    unregistered = replace(
        kept,
        invoice_number=f"LOST-{moment:%Y%m%d%H%M%S}-3",
        recipients=foreign(IdType.NOT_REGISTERED, "12345678Z", "ES"),
    )
    first = build(kept, installation, None, moment)
    second = build(refused, installation, link(kept, first), moment)
    third = build(unregistered, installation, link(refused, second), moment)
    submit(company, [first, second, third])

    resent = submission.build_submission(
        taxpayer_tax_id=company.tax_id,
        taxpayer_name=company.name,
        records=[first, second, third],
        incident=True,
    )
    stored, rejected, with_errors = send(resent).records
    assert (stored.error_code, stored.duplicate.status) == (3000, DuplicateStatus.VALID)
    assert not stored.needs_amendment
    assert (rejected.status, rejected.error_code) == (RecordStatus.REJECTED, 1124)
    assert with_errors.duplicate.status is DuplicateStatus.ACCEPTED_WITH_ERRORS
    assert with_errors.needs_amendment
