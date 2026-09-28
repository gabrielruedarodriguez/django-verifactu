import base64
import traceback
from datetime import date

import pytest

from django_verifactu import conf
from django_verifactu.conf import Taxpayer
from tests.settings import CERTIFICATE


def provider(tax_id):
    return Taxpayer("Proveedor SL", CERTIFICATE, "x") if tax_id == "89890001K" else None


def test_credentials_can_come_from_a_provider(settings):
    settings.VERIFACTU = {**settings.VERIFACTU, "TAXPAYERS": "tests.test_conf.provider"}
    assert conf.taxpayer("89890001K") == Taxpayer("Proveedor SL", CERTIFICATE, "x")
    with pytest.raises(LookupError):
        conf.taxpayer("89890002E")


def test_taxpayers_without_credentials_are_reported():
    with pytest.raises(LookupError):
        conf.taxpayer("B12345674")


def test_a_certificate_that_is_not_a_file_is_not_repeated_in_errors(settings):
    inline = base64.b64encode(CERTIFICATE).decode()
    entry = {"name": "E SL", "certificate": inline, "password": "x"}
    settings.VERIFACTU = {**settings.VERIFACTU, "TAXPAYERS": {"89890001K": entry}}
    with pytest.raises(OSError) as error:
        conf.taxpayer("89890001K")
    assert inline[:40] not in "".join(traceback.format_exception(error.value))


def test_certificates_can_be_read_from_a_file(settings, tmp_path):
    path = tmp_path / "company.p12"
    path.write_bytes(CERTIFICATE)
    end = date(2026, 12, 31)
    entry = {"name": "E SL", "certificate": str(path), "password": "x", "verifactu_end_date": end}
    settings.VERIFACTU = {**settings.VERIFACTU, "TAXPAYERS": {"89890001K": entry}}
    assert conf.taxpayer("89890001K") == Taxpayer("E SL", CERTIFICATE, "x", verifactu_end_date=end)
