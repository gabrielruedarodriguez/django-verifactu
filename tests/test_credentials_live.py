from dataclasses import replace
from datetime import date

import pytest
from django.db import transaction
from django.utils import timezone
from lxml import etree

from django_verifactu.aeat.domain import Party
from django_verifactu.conf import Taxpayer
from django_verifactu.issuing import register
from django_verifactu.models import Record
from django_verifactu.sending import send_pending
from django_verifactu.verifying import verify
from tests.aeat.live import credentials, now, requires_aeat, taxpayer
from tests.certificates import fake_pkcs12
from tests.conftest import invoice_of
from tests.shop.models import Sale

pytestmark = [requires_aeat, pytest.mark.django_db]


def provider(tax_id):
    company = taxpayer()
    certificate, password = credentials()
    return Taxpayer(company.name, certificate, password) if tax_id == company.tax_id else None


def several(tax_id):
    return True


def register_one(company, prefix, **changes):
    number = f"{prefix}-{now():%Y%m%d%H%M%S}"
    invoice = replace(invoice_of(company, number), **changes)
    with transaction.atomic():
        return register(Sale.objects.create(number=number), invoice)


def configure(settings, **changes):
    settings.VERIFACTU = {**settings.VERIFACTU, **changes}


def test_credentials_can_come_from_a_provider(company, settings):
    configure(settings, TAXPAYERS="tests.test_credentials_live.provider")
    register_one(company, "PROVIDER")
    [submission] = send_pending()
    assert (submission.outcome, Record.objects.get().status) == ("answered", "accepted")


def test_the_end_of_verifactu_is_accepted(company, settings):
    entry = settings.VERIFACTU["TAXPAYERS"][company.tax_id]
    end = date(now().year, 12, 31)
    configure(settings, TAXPAYERS={company.tax_id: {**entry, "verifactu_end_date": end}})
    register_one(company, "LEAVING")
    [submission] = send_pending()
    echoed = etree.fromstring(submission.response.encode()).findtext(".//{*}FechaFinVeriFactu")
    assert (echoed, Record.objects.get().status) == (f"{end:%d-%m-%Y}", "accepted")


def test_a_representative_is_declared_and_accepted(company, settings):
    entry = settings.VERIFACTU["TAXPAYERS"][company.tax_id]
    representative = Party(company.name, tax_id=company.tax_id)
    configure(settings, TAXPAYERS={company.tax_id: {**entry, "representative": representative}})
    register_one(company, "REPRESENTED")
    [submission] = send_pending()
    header = etree.fromstring(submission.response.encode()).find(".//{*}Representante")
    assert header is not None and header.findtext("{*}NIF") == company.tax_id
    assert Record.objects.get().status == "accepted"
    assert verify(aeat=True) == []


def test_a_system_serving_several_taxpayers_is_accepted(company, settings):
    configure(settings, MULTIPLE_TAXPAYERS="tests.test_credentials_live.several")
    record = register_one(company, "SEVERAL")
    indicator = etree.fromstring(record.xml).findtext(".//{*}IndicadorMultiplesOT")
    send_pending()
    assert (indicator, Record.objects.get().status) == ("S", "accepted")


def test_canary_islands_time_is_accepted_on_time(company, settings):
    configure(settings, TIME_ZONE="Atlantic/Canary")
    record = register_one(company, "CANARY")
    send_pending()
    offset = timezone.localtime(timezone.now(), record.generated_at.tzinfo).strftime("%z")
    stored = Record.objects.get()
    assert etree.fromstring(record.xml).findtext(".//{*}FechaHoraHusoGenRegistro").endswith(
        f"{offset[:3]}:{offset[3:]}"
    )
    assert (stored.status, stored.error_code) == ("accepted", None)


def test_a_refused_certificate_does_not_stop_the_other_taxpayers(company, settings):
    public_body = {"name": "Agencia Tributaria", "certificate": fake_pkcs12(), "password": "x"}
    configure(settings, TAXPAYERS={**settings.VERIFACTU["TAXPAYERS"], "Q2826000H": public_body})
    register_one(company, "REFUSED", issuer_tax_id="Q2826000H", issuer_name="Agencia Tributaria")
    register_one(company, "ACCEPTED")
    outcomes = {s.installation.taxpayer_tax_id: s for s in send_pending()}
    assert outcomes["Q2826000H"].outcome == "fault"
    assert "erro4011" in outcomes["Q2826000H"].response
    assert outcomes[company.tax_id].outcome == "answered"
