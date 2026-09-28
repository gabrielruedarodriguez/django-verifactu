from dataclasses import replace
from datetime import date, datetime

import pytest
from lxml import etree

from django_verifactu.aeat.codes import DuplicateStatus, Operation, RecordStatus, SubmissionStatus
from django_verifactu.aeat.domain import DuplicateRecord
from django_verifactu.aeat.schemas import get_schema
from django_verifactu.aeat.soap import (
    AeatFault,
    UnexpectedResponse,
    parse_response,
    wrap_in_envelope,
)
from django_verifactu.aeat.submission import build_submission
from tests.aeat.sample import (
    DUPLICATE,
    INVOICE,
    PRESENTATION,
    REJECTION,
    SOAP,
    error,
    response,
    response_line,
    sample_registration,
)

ACCEPTED = response("Correcto", response_line("Correcto"))
REJECTED = response("Incorrecto", response_line("Incorrecto", REJECTION))
WITH_ERRORS = response(
    "Correcto",
    response_line(
        "AceptadoConErrores", error(2000, "El cálculo de la huella suministrada es incorrecta.")
    ),
)
DUPLICATED = response("Incorrecto", response_line("Incorrecto", DUPLICATE))
MIXED = response(
    "ParcialmenteCorrecto",
    response_line("Correcto", invoice_number="A-1", reference="ERP-1"),
    response_line("Incorrecto", REJECTION, invoice_number="A-2"),
    presentation=PRESENTATION,
)


def fault(code: str, message: str = "Codigo[4102].El XML no cumple el esquema.") -> bytes:
    return f"""<env:Envelope xmlns:env="{SOAP}"><env:Body><env:Fault>
<faultcode>{code}</faultcode>
<faultstring>{message}</faultstring>
</env:Fault></env:Body></env:Envelope>""".encode()


def test_envelope_carries_the_submission_in_its_body():
    submission = build_submission(
        taxpayer_tax_id=INVOICE.issuer_tax_id,
        taxpayer_name=INVOICE.issuer_name,
        records=[sample_registration()],
    )
    body = etree.fromstring(wrap_in_envelope(submission)).find(f"{{{SOAP}}}Body")
    get_schema("SuministroLR").assertValid(body[0])


@pytest.mark.parametrize("sample", [ACCEPTED, REJECTED, WITH_ERRORS, DUPLICATED, MIXED])
def test_sample_responses_follow_the_official_schema(sample):
    answer = etree.fromstring(sample).find(f"{{{SOAP}}}Body")[0]
    get_schema("RespuestaSuministro").assertValid(answer)


def test_accepted_submission():
    result = parse_response(ACCEPTED)
    assert result.status is SubmissionStatus.ACCEPTED
    assert result.csv == "A-TEST-CSV"
    assert result.wait_seconds == 60
    [record] = result.records
    assert (record.issuer_tax_id, record.invoice_number, record.issue_date) == (
        "89890001K",
        "A-2026/001",
        date(2026, 9, 24),
    )
    assert record.operation is Operation.REGISTRATION
    assert record.status is RecordStatus.ACCEPTED
    assert record.error_code is None
    assert record.external_reference is None
    assert record.duplicate is None


def test_rejected_record_carries_the_aeat_error():
    [record] = parse_response(REJECTED).records
    assert record.status is RecordStatus.REJECTED
    assert record.error_code == 1100
    assert record.error_description == "Valor o tipo incorrecto del campo."


def test_record_accepted_with_errors():
    [record] = parse_response(WITH_ERRORS).records
    assert record.status is RecordStatus.ACCEPTED_WITH_ERRORS
    assert record.error_code == 2000


def test_duplicate_record_reports_the_stored_one():
    [record] = parse_response(DUPLICATED).records
    assert record.error_code == 3000
    assert record.duplicate == DuplicateRecord(
        request_id="20260924100005",
        status=DuplicateStatus.VALID,
        error_code=None,
        error_description=None,
    )


def test_lines_keep_their_order_and_the_presentation_time_is_read():
    result = parse_response(MIXED)
    assert result.status is SubmissionStatus.PARTIALLY_ACCEPTED
    assert [(r.invoice_number, r.status) for r in result.records] == [
        ("A-1", RecordStatus.ACCEPTED),
        ("A-2", RecordStatus.REJECTED),
    ]
    assert result.presented_at == datetime.fromisoformat("2026-09-24T10:00:05+02:00")
    assert result.presenter_tax_id == "12345678Z"
    assert [r.external_reference for r in result.records] == ["ERP-1", None]


@pytest.mark.parametrize(
    ("sample", "code", "expected"),
    [
        (WITH_ERRORS, 2000, True),
        (WITH_ERRORS, 2004, False),
        (WITH_ERRORS, 2009, False),
        (ACCEPTED, None, False),
        (REJECTED, 1100, False),
    ],
)
def test_only_some_records_accepted_with_errors_need_an_amendment(sample, code, expected):
    [record] = parse_response(sample).records
    assert replace(record, error_code=code).needs_amendment is expected


@pytest.mark.parametrize(
    ("code", "retryable"),
    [("env:Client", False), ("env:Server", True), ("soapenv:Server", True)],
)
def test_soap_fault_tells_whether_to_retry(code, retryable):
    with pytest.raises(AeatFault, match="4102") as raised:
        parse_response(fault(code))
    assert raised.value.fault_code == code
    assert raised.value.error_code == 4102
    assert raised.value.retryable is retryable


def test_soap_fault_without_an_aeat_code():
    with pytest.raises(AeatFault) as raised:
        parse_response(fault("env:Server", "Internal error"))
    assert raised.value.error_code is None


@pytest.mark.parametrize(
    "content", [b"", b"not xml", b"<html><body>Service unavailable</body></html>"]
)
def test_answers_that_are_not_aeat_responses_are_rejected(content):
    with pytest.raises(UnexpectedResponse):
        parse_response(content)


def test_external_entities_are_never_resolved(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    malicious = ACCEPTED.replace(
        b"<env:Envelope",
        f'<!DOCTYPE x [<!ENTITY leak SYSTEM "{secret.as_uri()}">]><env:Envelope'.encode(),
        1,
    ).replace(b"A-TEST-CSV", b"&leak;")
    assert "TOP-SECRET" not in (parse_response(malicious).csv or "")


def test_duplicates_tell_whether_the_stored_record_needs_an_amendment():
    [record] = parse_response(DUPLICATED).records
    assert not record.needs_amendment
    stored_with_errors = replace(
        record.duplicate, status=DuplicateStatus.ACCEPTED_WITH_ERRORS, error_code=2001
    )
    assert replace(record, duplicate=stored_with_errors).needs_amendment
    stored_late = replace(stored_with_errors, error_code=2004)
    assert not replace(record, duplicate=stored_late).needs_amendment
