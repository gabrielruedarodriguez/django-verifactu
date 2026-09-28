from dataclasses import dataclass, field, replace
from datetime import timedelta
from itertools import count

import pytest
from django.db import transaction
from django.utils import timezone
from lxml import etree

from django_verifactu import sending
from django_verifactu.aeat.codes import StoredStatus
from django_verifactu.aeat.domain import InvoiceId, Party, StoredRecord
from django_verifactu.aeat.elements import RECORDS, tag
from django_verifactu.issuing import register
from tests.aeat.live import CERTIFICATE, credentials, now, taxpayer
from tests.aeat.sample import INVOICE, SOFTWARE, response, response_line
from tests.shop.models import Sale

REAL_NOW = timezone.now


@dataclass
class FakeAeat:
    answers: dict = field(default_factory=dict)
    failure: Exception | None = None
    content: bytes | None = None
    calls: list = field(default_factory=list)
    incidents: list = field(default_factory=list)

    def __call__(self, element, **kwargs):
        ids = element.iterfind(f".//{tag(RECORDS, 'IDFactura')}")
        invoices = [(invoice[0].text, invoice[1].text, _operation(invoice)) for invoice in ids]
        self.calls.append([number for _, number, _ in invoices])
        self.incidents.append(element.findtext(f".//{tag(RECORDS, 'Incidencia')}") == "S")
        if self.failure:
            raise self.failure
        if self.content:
            return self.content
        lines = [
            response_line(
                *self.answers.get(number, ("Correcto",)),
                invoice_number=number,
                issuer=issuer,
                operation=operation,
            )
            for issuer, number, operation in invoices
        ]
        return response("Correcto", *lines)


def _operation(invoice_id) -> str:
    return etree.QName(invoice_id.getparent()).localname.removeprefix("Registro")


def flags(record):
    element = etree.fromstring(record.xml)
    names = ("Subsanacion", "RechazoPrevio", "SinRegistroPrevio")
    values = {name: element.findtext(f"{{*}}{name}") for name in names}
    return etree.QName(element).localname, {name: v for name, v in values.items() if v}


def alta(**flags):
    return "RegistroAlta", flags


def anulacion(**flags):
    return "RegistroAnulacion", flags


@pytest.fixture
def aeat(monkeypatch):
    fake = FakeAeat()
    monkeypatch.setattr(sending, "post", fake)
    monkeypatch.setattr(sending, "client_ssl_context", lambda *args: None)
    return fake


@pytest.fixture
def send(monkeypatch):
    # Each pass waits out the AEAT's 60 seconds on a shifted clock, inside the 240 s of 2004.
    passes = count()

    def send():
        moment = REAL_NOW() + timedelta(seconds=61 * next(passes))
        monkeypatch.setattr(timezone, "now", lambda: moment)
        return sending.send_pending()

    return send


def stored(record, *, fingerprint=None, installation_number=None, status=StoredStatus.ACCEPTED):
    installation_number = installation_number or record.installation.number
    return StoredRecord(
        invoice=InvoiceId(
            record.installation.taxpayer_tax_id, record.invoice_number, record.issue_date
        ),
        status=status,
        error_code=None,
        error_description=None,
        modified_at=timezone.now(),
        invoice_type=None,
        description=None,
        total_tax=None,
        total_amount=None,
        external_reference=None,
        issuer_name=None,
        software=replace(SOFTWARE, installation_number=installation_number),
        generated_at=None,
        fingerprint=fingerprint or record.fingerprint,
        presented_at=None,
        presenter_tax_id=None,
        request_id=None,
    )


def registered(*numbers, issuer="89890001K"):
    with transaction.atomic():
        return [
            register(
                Sale.objects.create(number=number),
                replace(INVOICE, invoice_number=number, issuer_tax_id=issuer),
            )
            for number in numbers
        ]


@pytest.fixture
def company(settings):
    company = taxpayer()
    owner = Party(company.name, tax_id=company.tax_id)
    _, password = credentials()
    settings.VERIFACTU = {
        **settings.VERIFACTU,
        "SOFTWARE": {**settings.VERIFACTU["SOFTWARE"], "producer": owner},
        "TAXPAYERS": {
            company.tax_id: {"name": company.name, "certificate": CERTIFICATE, "password": password}
        },
    }
    return company


def invoice_of(company, number):
    owner = Party(company.name, tax_id=company.tax_id)
    return replace(
        INVOICE,
        issuer_tax_id=company.tax_id,
        issuer_name=company.name,
        invoice_number=number,
        issue_date=now().date(),
        recipients=(owner,),
    )
