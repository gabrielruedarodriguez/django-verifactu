import re
from dataclasses import replace
from decimal import Decimal

import pytest
from lxml import etree

from django_verifactu.aeat.codes import CorrectionType, InvoiceType
from django_verifactu.aeat.domain import InvoiceId, TaxLine
from django_verifactu.aeat.qr import qr_code, qr_svg, qr_url
from django_verifactu.aeat.records import build_registration_record
from tests.aeat.sample import (
    GENERATED_AT,
    INVOICE,
    SOFTWARE,
    sample_cancellation,
    sample_registration,
)


def record_of(invoice):
    return build_registration_record(
        invoice=invoice, software=SOFTWARE, previous=None, generated_at=GENERATED_AT
    )


def test_url_carries_the_values_of_the_registration_record():
    assert qr_url(sample_registration(), production=False) == (
        "https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR"
        "?nif=89890001K&numserie=A-2026%2F001&fecha=24-09-2026&importe=121.00"
    )


def test_official_url_encoding_example():
    record = record_of(replace(INVOICE, invoice_number="12345678&G33"))
    assert "&numserie=12345678%26G33&" in qr_url(record, production=False)


def test_negative_totals_keep_their_sign():
    credit = replace(
        INVOICE,
        invoice_type=InvoiceType.R4,
        correction_type=CorrectionType.DIFFERENCES,
        corrected_invoices=(InvoiceId("89890001K", "A-2026/000", INVOICE.issue_date),),
        lines=(TaxLine(base=Decimal(-100), rate=Decimal(21), tax=Decimal(-21)),),
    )
    assert qr_url(record_of(credit), production=False).endswith("&importe=-121.00")


def test_production_url():
    assert qr_url(sample_registration(), production=True).startswith(
        "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR?nif=89890001K&"
    )


def test_cancellations_have_no_qr():
    with pytest.raises(ValueError):
        qr_url(sample_cancellation(), production=False)


SHORT_URL = qr_url(sample_registration(), production=False)
LONG_URL = qr_url(record_of(replace(INVOICE, invoice_number="A/" * 30)), production=True)


def width_mm(svg: str) -> float:
    return float(re.search(r'width="([0-9.]+)mm"', svg).group(1))


@pytest.mark.parametrize("url", [SHORT_URL, LONG_URL])
def test_image_is_between_30_and_40_mm_with_a_quiet_zone_of_at_least_2_mm(url):
    width = width_mm(qr_svg(url))
    assert 30 <= width <= 40
    assert (width - 32) / 2 >= 2


def test_symbol_is_a_full_qr_code_with_error_correction_level_m():
    code = qr_code(LONG_URL)
    assert code.error == "M"
    assert not code.is_micro


def test_image_is_a_standalone_black_on_white_svg():
    svg = etree.fromstring(qr_svg(SHORT_URL).encode())
    assert svg.tag == "{http://www.w3.org/2000/svg}svg"
    colours = {(path.get("fill"), path.get("stroke")) for path in svg.iter("{*}path")}
    assert colours == {("#fff", None), (None, "#000")}
