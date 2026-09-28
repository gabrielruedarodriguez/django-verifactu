from dataclasses import replace

import pytest

from django_verifactu.aeat.codes import GeneratedBy, IdType
from django_verifactu.aeat.domain import ForeignId, Party
from django_verifactu.aeat.records import build_cancellation_record
from django_verifactu.aeat.schemas import get_schema
from django_verifactu.aeat.validation import validate_cancellation
from django_verifactu.aeat.violations import ValidationError
from tests.aeat.sample import CANCELLATION, GENERATED_AT, INVOICE, SOFTWARE

RECIPIENT = Party("Cliente", tax_id="12345678Z")


def codes(**changes):
    return [violation.code for violation in validate_cancellation(replace(CANCELLATION, **changes))]


def build(**changes):
    return build_cancellation_record(
        cancellation=replace(CANCELLATION, **changes),
        software=SOFTWARE,
        previous=None,
        generated_at=GENERATED_AT,
    )


def value(record, path: str) -> str:
    return record.findtext(path, namespaces={"sf": record.nsmap["sum1"]})


def foreign(id_type, country):
    return Party("Cliente", foreign_id=ForeignId(id_type, "AB123456", country))


def test_sample_cancellation_is_valid():
    assert codes() == []


@pytest.mark.parametrize(
    ("number", "expected"),
    [("", [1104]), ("A" * 61, [1104]), ("Añ1", [1130]), ("A=1", [1287])],
)
def test_cancelled_invoice_number_follows_the_invoice_number_rules(number, expected):
    assert codes(invoice_number=number) == expected


def test_external_reference_has_at_most_60_characters():
    assert codes(external_reference="x" * 60) == []
    assert codes(external_reference="x" * 61) == [1253]


def test_generator_goes_with_generated_by():
    assert codes(generated_by=GeneratedBy.RECIPIENT, generator=RECIPIENT) == []
    assert codes(generated_by=GeneratedBy.RECIPIENT) == [1224]
    assert codes(generator=RECIPIENT) == [1224]


@pytest.mark.parametrize(
    ("generated_by", "generator", "expected"),
    [
        (GeneratedBy.ISSUER, foreign(IdType.PASSPORT, "FR"), [1227]),
        (GeneratedBy.RECIPIENT, Party("Emisor", tax_id=INVOICE.issuer_tax_id), [1259]),
        (GeneratedBy.THIRD_PARTY, foreign(IdType.NOT_REGISTERED, "ES"), [1229]),
        (GeneratedBy.RECIPIENT, foreign(IdType.OFFICIAL_ID, "ES"), [1234]),
        (GeneratedBy.THIRD_PARTY, foreign(IdType.OFFICIAL_ID, "ES"), [1232]),
        (GeneratedBy.RECIPIENT, foreign(IdType.PASSPORT, "ES"), []),
        (GeneratedBy.THIRD_PARTY, foreign(IdType.PASSPORT, "FR"), []),
    ],
)
def test_generator_identification(generated_by, generator, expected):
    assert codes(generated_by=generated_by, generator=generator) == expected


def test_plain_cancellation_has_no_optional_fields():
    record = build()
    for name in ("RefExterna", "SinRegistroPrevio", "RechazoPrevio", "GeneradoPor"):
        assert value(record, f"sf:{name}") is None


def test_cancellation_record_carries_every_optional_field_in_order():
    record = build(
        external_reference="ERP-1",
        without_previous_record=True,
        previous_rejection=True,
        generated_by=GeneratedBy.RECIPIENT,
        generator=RECIPIENT,
    )
    get_schema("SuministroInformacion").assertValid(record)
    assert value(record, "sf:RefExterna") == "ERP-1"
    assert value(record, "sf:SinRegistroPrevio") == "S"
    assert value(record, "sf:RechazoPrevio") == "S"
    assert value(record, "sf:GeneradoPor") == "D"
    assert value(record, "sf:Generador/sf:NIF") == "12345678Z"


@pytest.mark.parametrize("issuer", ["89890001A", "89890001k", ""])
def test_the_issuer_needs_a_valid_nif(issuer):
    assert codes(issuer_tax_id=issuer) == [1123]


def test_invalid_cancellation_cannot_become_a_record():
    with pytest.raises(ValidationError):
        build(generated_by=GeneratedBy.RECIPIENT)


def test_cancellation_checks_the_software():
    with pytest.raises(ValidationError) as error:
        build_cancellation_record(
            cancellation=CANCELLATION,
            software=replace(SOFTWARE, system_id="fa"),
            previous=None,
            generated_at=GENERATED_AT,
        )
    assert [violation.code for violation in error.value.violations] == [1177]
