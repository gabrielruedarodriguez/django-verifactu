import re

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_ENTITY_CONTROL_LETTERS = "JABCDEFGHI"
_NIE_PREFIXES = {"X": "0", "Y": "1", "Z": "2"}

# EU VAT number structures published by the AEAT (Validaciones VERI*FACTU, note 1).
_VAT_NUMBERS = {
    prefix: re.compile(pattern)
    for prefix, pattern in {
        "AT": r"[0-9A-Z]{9}",
        "BE": r"\d{10}",
        "BG": r"\d{9,10}",
        "CY": r"[0-9A-Z]{9}",
        "CZ": r"\d{8,10}",
        "DE": r"\d{9}",
        "DK": r"\d{8}",
        "EE": r"\d{9}",
        "EL": r"\d{9}",
        "FI": r"\d{8}",
        "FR": r"[0-9A-Z]{11}",
        "GB": r"[0-9A-Z]{5}|[0-9A-Z]{9}|[0-9A-Z]{12}",
        "HR": r"\d{11}",
        "HU": r"\d{8}",
        "IE": r"[0-9A-Z]{8,9}",
        "IT": r"\d{11}",
        "LT": r"\d{9}|\d{12}",
        "LU": r"\d{8}",
        "LV": r"\d{11}",
        "MT": r"\d{8}",
        "NL": r"[0-9A-Z]{12}",
        "PL": r"\d{10}",
        "PT": r"\d{9}",
        "RO": r"[1-9]\d{1,9}",
        "SE": r"\d{12}",
        "SI": r"\d{8}",
        "SK": r"\d{10}",
        "XI": r"[0-9A-Z]{5}|[0-9A-Z]{9}|[0-9A-Z]{12}",
    }.items()
}


# Verified live: the AEAT refuses as badly formatted the NIFs whose number is zero.
def is_valid_nif(nif: str) -> bool:
    return is_natural_person_nif(nif) or _is_entity_nif(nif)


def is_natural_person_nif(nif: str) -> bool:
    if re.fullmatch(r"\d{8}[A-Z]", nif):
        number = nif[:8]
    elif re.fullmatch(r"[XYZ]\d{7}[A-Z]", nif):
        number = _NIE_PREFIXES[nif[0]] + nif[1:8]
    elif re.fullmatch(r"[KLM]\d{7}[A-Z]", nif):
        number = nif[1:8]
    else:
        return False
    return int(number) > 0 and nif[-1] == _DNI_LETTERS[int(number) % 23]


def is_valid_vat_number(vat_number: str) -> bool:
    pattern = _VAT_NUMBERS.get(vat_number[:2])
    return pattern is not None and pattern.fullmatch(vat_number[2:]) is not None


def _is_entity_nif(nif: str) -> bool:
    if not re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", nif):
        return False
    digits = [int(digit) for digit in nif[1:8]]
    if not any(digits):
        return False
    total = sum(digits[1::2]) + sum(sum(divmod(2 * digit, 10)) for digit in digits[::2])
    control = (10 - total % 10) % 10
    return nif[-1] in (str(control), _ENTITY_CONTROL_LETTERS[control])
