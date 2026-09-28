from dataclasses import replace
from datetime import date

import pytest

from django_verifactu.aeat.codes import IdType
from django_verifactu.aeat.domain import ForeignId, Party
from django_verifactu.aeat.records import build_registration_record
from django_verifactu.aeat.schemas import get_schema
from django_verifactu.aeat.validation import validate_software
from django_verifactu.aeat.violations import ValidationError
from tests.aeat.sample import GENERATED_AT, INVOICE, SOFTWARE

TAX_DATE = date(2026, 9, 24)


def codes(**changes):
    violations = validate_software(replace(SOFTWARE, **changes), TAX_DATE)
    return [violation.code for violation in violations]


def foreign(id_type, number, country=None):
    return Party("Software House", foreign_id=ForeignId(id_type, number, country))


def build(**changes):
    return build_registration_record(
        invoice=INVOICE,
        software=replace(SOFTWARE, **changes),
        previous=None,
        generated_at=GENERATED_AT,
    )


def test_sample_software_is_valid():
    assert codes() == []


@pytest.mark.parametrize(
    ("producer", "expected"),
    [
        (Party("Productor", tax_id="89890001A"), [4109]),
        (Party("Productor", tax_id="00000000T"), [4109]),
        (Party("Productor"), [4102]),
        (replace(foreign(IdType.PASSPORT, "AB123456", "FR"), tax_id="89890003T"), [4102]),
        (foreign(IdType.VAT_NUMBER, "IE6388047V"), []),
        (foreign(IdType.VAT_NUMBER, "DE12345"), [1103]),
        (foreign(IdType.VAT_NUMBER, "IE6388047V", "FR"), [1122]),
        (foreign(IdType.VAT_NUMBER, "GB123456789"), [1255]),
        (foreign(IdType.PASSPORT, "AB123456", "ES"), []),
        (foreign(IdType.PASSPORT, "AB123456", "FR"), []),
        (foreign(IdType.OFFICIAL_ID, "X1234567", "ES"), [1232]),
        (foreign(IdType.NOT_REGISTERED, "12345678Z", "ES"), [1221]),
        (foreign(IdType.OFFICIAL_ID, "X1"), [1111]),
        (foreign(IdType.OTHER_DOCUMENT, "EIN-12-3456789", "US"), []),
    ],
)
def test_producer_identification(producer, expected):
    assert codes(producer=producer) == expected


@pytest.mark.parametrize(
    ("system_id", "expected"),
    [
        ("FA", []),
        ("09", []),
        ("A", [1177]),
        ("fa", [1177]),
        ("Ñ1", [1177]),
        ("A-", [1177]),
        ("", []),
        ("ABC", []),
    ],
)
def test_system_id_is_two_uppercase_letters_or_digits(system_id, expected):
    assert codes(system_id=system_id) == expected


def test_multiple_taxpayers_indicator_does_not_depend_on_the_possibility():
    assert codes(multiple_taxpayers_possible=False, multiple_taxpayers=True) == []


def test_foreign_producer_is_written_with_its_id():
    record = build(producer=foreign(IdType.OTHER_DOCUMENT, "EIN-1", "US"))
    get_schema("SuministroInformacion").assertValid(record)
    foreign_id = record.find("sf:SistemaInformatico/sf:IDOtro", {"sf": record.nsmap["sum1"]})
    assert [element.text for element in foreign_id] == ["US", "06", "EIN-1"]


@pytest.mark.parametrize(
    "change",
    [
        {"name": " "},
        {"system_id": ""},
        {"system_id": "ABC"},
        {"version": ""},
        {"installation_number": " "},
        {"producer": Party(" ", tax_id="89890003T")},
    ],
)
def test_blank_or_too_long_software_fields_are_refused(change):
    with pytest.raises(ValidationError) as error:
        build(**change)
    assert [violation.code for violation in error.value.violations] == [1100]


def test_invalid_software_cannot_become_a_record():
    with pytest.raises(ValidationError):
        build(system_id="fa")
