from pathlib import Path

import pytest
from lxml import etree

from django_verifactu.aeat.schemas import get_schema

EXAMPLE = Path(__file__).parent / "fixtures" / "ejemploRegistro.xml"


def test_official_example_is_valid():
    get_schema("SuministroInformacion").assertValid(etree.parse(EXAMPLE))


def test_invalid_invoice_type_is_rejected():
    doc = etree.parse(EXAMPLE)
    doc.find(".//{*}TipoFactura").text = "XX"
    with pytest.raises(etree.DocumentInvalid):
        get_schema("SuministroInformacion").assertValid(doc)


def test_submission_schema_compiles_without_network():
    assert get_schema("SuministroLR") is not None
