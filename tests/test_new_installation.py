from dataclasses import replace
from datetime import timedelta
from io import StringIO

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError, call_command
from django.db import transaction
from django.utils import timezone
from lxml import etree

from django_verifactu import sending
from django_verifactu.aeat import submission
from django_verifactu.issuing import amend, cancel, new_installation
from django_verifactu.models import Installation, Record
from django_verifactu.sending import send_pending
from django_verifactu.verifying import verify
from tests.aeat.sample import CANCELLATION, INVOICE
from tests.conftest import registered

pytestmark = pytest.mark.django_db
REAL_NOW = timezone.now


def later(monkeypatch, seconds):
    moment = REAL_NOW() + timedelta(seconds=seconds)
    monkeypatch.setattr(timezone, "now", lambda: moment)


def first_in_chain(record) -> bool:
    return etree.fromstring(record.xml).findtext(".//{*}PrimerRegistro") == "S"


def test_a_new_installation_restarts_the_chain():
    [old] = registered("A-1")
    installation = new_installation("89890001K")
    [record] = registered("A-2")
    assert (installation.generation, record.installation) == (2, installation)
    assert (record.position, first_in_chain(record)) == (1, True)
    assert installation.number != old.installation.number
    assert verify() == []


def test_invoices_of_an_earlier_generation_keep_their_lifecycle():
    [old] = registered("A-1")
    new_installation("89890001K")
    record = amend(old.content_object, replace(INVOICE, invoice_number="A-1"))
    assert (record.amendment, record.installation.generation) == (True, 2)


def test_earlier_generations_are_still_sent(aeat, send):
    registered("A-1")
    new_installation("89890001K")
    registered("A-2")
    send()
    send()
    assert aeat.calls == [["A-1"], ["A-2"]]
    assert set(Record.objects.values_list("status", flat=True)) == {"accepted"}


def test_a_new_installation_takes_the_current_software(settings):
    registered("A-1")
    software = {**settings.VERIFACTU["SOFTWARE"], "system_id": "FB"}
    settings.VERIFACTU = {**settings.VERIFACTU, "SOFTWARE": software}
    with pytest.raises(ImproperlyConfigured):
        registered("A-2")
    assert new_installation("89890001K").system_id == "FB"
    [record] = registered("A-2")
    assert ">FB<" in record.xml


@pytest.mark.parametrize("tax_id", ["89890001A", "89890001K"])
def test_only_existing_chains_can_be_restarted(tax_id):
    with pytest.raises(ValueError):
        new_installation(tax_id)
    assert not Installation.objects.exists()


def test_older_generations_are_sent_before_newer_ones(aeat, monkeypatch):
    monkeypatch.setattr(sending, "MAX_RECORDS", 2)
    monkeypatch.setattr(submission, "MAX_RECORDS", 2)
    registered("A-0")
    send_pending()
    [old] = registered("A-1")
    new_installation("89890001K")
    with transaction.atomic():
        cancel(old.content_object, replace(CANCELLATION, invoice_number="A-1"))
    registered("A-2")
    # A full batch is due at once, but it cancels an invoice the AEAT has not received yet.
    send_pending()
    assert aeat.calls == [["A-0"]]
    later(monkeypatch, 61)
    send_pending()
    assert aeat.calls == [["A-0"], ["A-1"]]


def test_the_command_starts_a_new_installation():
    registered("A-1")
    out = StringIO()
    call_command("verifactu_new_installation", "89890001K", stdout=out)
    installation = Installation.objects.get(generation=2)
    assert installation.number in out.getvalue()
    with pytest.raises(CommandError):
        call_command("verifactu_new_installation", "89890001A", stdout=StringIO())
