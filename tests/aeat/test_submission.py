from datetime import UTC, date, datetime, timedelta

import pytest

from django_verifactu.aeat.domain import Party
from django_verifactu.aeat.schemas import get_schema
from django_verifactu.aeat.submission import (
    build_submission,
    submission_allowed,
    validate_header,
    validate_submission,
)
from django_verifactu.aeat.violations import ValidationError
from tests.aeat.sample import (
    INVOICE,
    sample_cancellation,
    sample_registration,
)

REGISTRATION = sample_registration()
CANCELLATION = sample_cancellation()
TODAY = date(2026, 9, 24)


def submit(records, **options):
    return build_submission(
        taxpayer_tax_id=INVOICE.issuer_tax_id,
        taxpayer_name=INVOICE.issuer_name,
        records=records,
        **options,
    )


def value(submission, path: str) -> str:
    return submission.findtext(path, namespaces=submission.nsmap)


def codes(today=TODAY, **changes):
    arguments = {
        "taxpayer_tax_id": INVOICE.issuer_tax_id,
        "taxpayer_name": INVOICE.issuer_name,
        "records": [REGISTRATION],
    }
    violations = validate_submission(**(arguments | changes), today=today)
    return [violation.code for violation in violations]


def test_submission_with_both_record_kinds_is_valid():
    get_schema("SuministroLR").assertValid(submit([REGISTRATION, CANCELLATION]))


def test_submission_leaves_the_given_records_untouched():
    submit([REGISTRATION])
    assert REGISTRATION.getparent() is None


@pytest.mark.parametrize(("count", "expected"), [(0, [4102]), (1001, [4114])])
def test_submission_needs_between_1_and_1000_records(count, expected):
    with pytest.raises(ValidationError) as error:
        submit([REGISTRATION] * count)
    assert [violation.code for violation in error.value.violations] == expected


def test_submission_with_a_representative():
    submission = submit([REGISTRATION], representative=Party("Asesoria", tax_id="12345678Z"))
    get_schema("SuministroLR").assertValid(submission)
    assert value(submission, "sum:Cabecera/sum1:Representante/sum1:NIF") == "12345678Z"


VOLUNTARY = "sum:Cabecera/sum1:RemisionVoluntaria"
END = date(date.today().year, 12, 31)


def test_voluntary_submission_block_is_only_written_when_needed():
    assert value(submit([REGISTRATION]), VOLUNTARY) is None


def test_incident_is_declared_alone():
    submission = submit([REGISTRATION], incident=True)
    get_schema("SuministroLR").assertValid(submission)
    assert value(submission, f"{VOLUNTARY}/sum1:Incidencia") == "S"
    assert value(submission, f"{VOLUNTARY}/sum1:FechaFinVeriFactu") is None


def test_end_of_verifactu_is_declared_alone():
    submission = submit([REGISTRATION], verifactu_end_date=END)
    get_schema("SuministroLR").assertValid(submission)
    assert value(submission, f"{VOLUNTARY}/sum1:FechaFinVeriFactu") == f"31-12-{END.year}"
    assert value(submission, f"{VOLUNTARY}/sum1:Incidencia") is None


def test_wrong_end_of_verifactu_cannot_be_submitted():
    with pytest.raises(ValidationError) as error:
        submit([REGISTRATION], verifactu_end_date=END.replace(year=END.year + 1))
    assert [violation.code for violation in error.value.violations] == [4120]


@pytest.mark.parametrize(
    "changes",
    [
        {"taxpayer_name": " "},
        {"taxpayer_name": "x" * 121},
        {"representative": Party(" ", tax_id="12345678Z")},
        {"representative": Party("x" * 121, tax_id="12345678Z")},
    ],
)
def test_header_names_are_not_blank_and_have_at_most_120_characters(changes):
    assert codes(**changes) == [1100]


@pytest.mark.parametrize(
    ("end_date", "expected"),
    [
        (date(2026, 12, 31), []),
        (date(2025, 12, 31), []),
        (date(2026, 6, 30), []),
        (date(2027, 12, 31), [4120]),
        (date(2024, 12, 31), [4120]),
    ],
)
def test_verifactu_ends_this_year_or_the_last_one(end_date, expected):
    assert codes(verifactu_end_date=end_date) == expected


def test_the_header_is_checked_on_its_own():
    representative = Party("Gestor", tax_id="12345678A")
    violations = validate_header(
        taxpayer_tax_id="89890001A",
        taxpayer_name=" ",
        representative=representative,
        verifactu_end_date=date(2027, 12, 31),
        today=TODAY,
    )
    assert [violation.code for violation in violations] == [4116, 1100, 4123, 4120]


def test_from_2027_verifactu_ends_on_31_december():
    assert codes(verifactu_end_date=date(2027, 6, 30), today=date(2027, 3, 1)) == [4120]
    assert codes(verifactu_end_date=date(2027, 12, 31), today=date(2027, 3, 1)) == []


NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("pending", "seconds_ago", "wait_seconds", "expected"),
    [
        (0, None, 60, False),
        (1, None, 60, True),
        (1, 59, 60, False),
        (1, 60, 60, True),
        (1, 100, 120, False),
        (999, 1, 60, False),
        (1000, 1, 60, True),
    ],
)
def test_flow_control_waits_the_aeat_time_or_a_full_submission(
    pending, seconds_ago, wait_seconds, expected
):
    last_sent_at = None if seconds_ago is None else NOW - timedelta(seconds=seconds_ago)
    allowed = submission_allowed(
        pending=pending, last_sent_at=last_sent_at, wait_seconds=wait_seconds, now=NOW
    )
    assert allowed is expected
