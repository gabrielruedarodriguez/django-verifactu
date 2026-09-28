import pytest

from django_verifactu.aeat.identifiers import (
    is_natural_person_nif,
    is_valid_nif,
    is_valid_vat_number,
)


@pytest.mark.parametrize(
    "nif", ["12345678Z", "89890001K", "X1234567L", "K1234567L", "Y0000000Z", "00000001R"]
)
def test_natural_person_nifs(nif):
    assert is_valid_nif(nif)
    assert is_natural_person_nif(nif)


@pytest.mark.parametrize("nif", ["B12345674", "Q1234567D", "B00000018"])
def test_entity_nifs(nif):
    assert is_valid_nif(nif)
    assert not is_natural_person_nif(nif)


@pytest.mark.parametrize(
    "nif", ["12345678A", "B12345675", "1234567Z", "X1234567A", "", "ABCDEFGHI"]
)
def test_invalid_nifs(nif):
    assert not is_valid_nif(nif)


@pytest.mark.parametrize("nif", ["00000000T", "X0000000T", "K0000000T", "B00000000", "A00000000"])
def test_nifs_numbered_zero_are_invalid(nif):
    assert not is_valid_nif(nif)


@pytest.mark.parametrize(
    "vat_number", ["DE123456789", "FRAB123456789", "EL123456789", "XI123456789", "RO1234"]
)
def test_valid_eu_vat_numbers(vat_number):
    assert is_valid_vat_number(vat_number)


@pytest.mark.parametrize(
    "vat_number", ["DE12345678", "US123456789", "RO0123", "de123456789", "ES12345678Z"]
)
def test_invalid_eu_vat_numbers(vat_number):
    assert not is_valid_vat_number(vat_number)
