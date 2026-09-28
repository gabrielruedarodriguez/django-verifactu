from dataclasses import replace
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.transaction import TransactionManagementError
from django.utils import timezone
from lxml import etree

from django_verifactu.aeat.codes import PreviousRejection
from django_verifactu.aeat.violations import ValidationError
from django_verifactu.issuing import AlreadyRegistered, register
from django_verifactu.models import ImmutableRecord, Installation, Record
from django_verifactu.signals import record_created
from tests.aeat.sample import INVOICE
from tests.shop.models import Note, Sale

pytestmark = pytest.mark.django_db


def sale(number="A-2026/001"):
    return Sale.objects.create(number=number)


def invoice(number="A-2026/001", **changes):
    return replace(INVOICE, invoice_number=number, **changes)


def value(record: Record, path: str) -> str | None:
    element = etree.fromstring(record.xml)
    return element.findtext(path, namespaces={"sf": element.nsmap["sum1"]})


def test_first_record_starts_the_chain():
    record = register(sale(), invoice())
    assert record.position == 1
    assert record.status == Record.Status.PENDING
    assert value(record, "sf:Encadenamiento/sf:PrimerRegistro") == "S"
    assert value(record, "sf:Huella") == record.fingerprint
    assert record.installation.number == value(record, "sf:SistemaInformatico/sf:NumeroInstalacion")


def test_next_record_links_to_the_previous_one():
    first = register(sale("A-1"), invoice("A-1"))
    second = register(sale("A-2"), invoice("A-2"))
    assert second.position == 2
    link = "sf:Encadenamiento/sf:RegistroAnterior"
    assert value(second, f"{link}/sf:NumSerieFactura") == "A-1"
    assert value(second, f"{link}/sf:Huella") == first.fingerprint


def test_record_is_linked_to_the_object():
    obj = sale()
    record = register(obj, invoice())
    assert record.content_object == obj
    assert list(obj.verifactu_records.all()) == [record]


def test_one_installation_per_taxpayer_and_environment():
    register(sale("A-1"), invoice("A-1"))
    register(sale("B-1"), invoice("B-1", issuer_tax_id="89890002E", issuer_name="Otro SL"))
    first, second = Installation.objects.order_by("id")
    assert (first.taxpayer_tax_id, second.taxpayer_tax_id) == ("89890001K", "89890002E")
    assert first.number != second.number
    assert not first.production


def test_a_second_taxpayer_marks_multiple_taxpayers(settings):
    alone = {"89890001K": settings.VERIFACTU["TAXPAYERS"]["89890001K"]}
    settings.VERIFACTU = {**settings.VERIFACTU, "TAXPAYERS": alone}
    first = register(sale("A-1"), invoice("A-1"))
    other = register(sale("B-1"), invoice("B-1", issuer_tax_id="89890002E", issuer_name="O SL"))
    assert value(first, "sf:SistemaInformatico/sf:IndicadorMultiplesOT") == "N"
    assert value(other, "sf:SistemaInformatico/sf:IndicadorMultiplesOT") == "S"


def test_configured_taxpayers_count_before_they_issue_anything():
    first = register(sale("A-1"), invoice("A-1"))
    assert value(first, "sf:SistemaInformatico/sf:IndicadorMultiplesOT") == "S"


def several(tax_id):
    return True


def alone(tax_id):
    return False


def test_the_multiple_taxpayers_indicator_can_come_from_the_integrator(settings):
    indicator = "sf:SistemaInformatico/sf:IndicadorMultiplesOT"
    settings.VERIFACTU = {**settings.VERIFACTU, "MULTIPLE_TAXPAYERS": "tests.test_register.several"}
    assert value(register(sale("A-1"), invoice("A-1")), indicator) == "S"
    settings.VERIFACTU = {**settings.VERIFACTU, "MULTIPLE_TAXPAYERS": "tests.test_register.alone"}
    other = register(sale("B-1"), invoice("B-1", issuer_tax_id="89890002E", issuer_name="O SL"))
    assert value(other, indicator) == "N"


def test_single_taxpayer_software_cannot_serve_several(settings):
    software = {**settings.VERIFACTU["SOFTWARE"], "multiple_taxpayers_possible": False}
    hook = "tests.test_register.several"
    settings.VERIFACTU = {**settings.VERIFACTU, "SOFTWARE": software, "MULTIPLE_TAXPAYERS": hook}
    with pytest.raises(ImproperlyConfigured):
        register(sale(), invoice())


def test_rolled_back_records_leave_no_trace():
    with pytest.raises(RuntimeError), transaction.atomic():
        register(sale("A-1"), invoice("A-1"))
        raise RuntimeError
    assert not Record.objects.exists()
    assert register(sale("A-2"), invoice("A-2")).position == 1


def test_invalid_invoices_write_nothing():
    with pytest.raises(ValidationError):
        register(sale(), invoice(description=""))
    assert not Record.objects.exists()
    assert not Installation.objects.exists()


def test_an_invoice_is_registered_once():
    register(sale(), invoice())
    with pytest.raises(AlreadyRegistered):
        register(sale(), invoice())


@pytest.mark.parametrize(
    "changes", [{"amendment": True}, {"previous_rejection": PreviousRejection.NO}]
)
def test_lifecycle_flags_are_decided_by_the_library(changes):
    with pytest.raises(ValueError):
        register(sale(), invoice(**changes))


def test_objects_need_a_verifactu_records_field():
    with pytest.raises(ImproperlyConfigured):
        register(Note.objects.create(text="x"), invoice())


def test_objects_must_be_saved():
    with pytest.raises(ImproperlyConfigured):
        register(Sale(number="A-1"), invoice())


@pytest.mark.django_db(transaction=True)
def test_registering_happens_inside_the_callers_transaction():
    with pytest.raises(TransactionManagementError):
        register(sale(), invoice())


@pytest.mark.django_db(transaction=True)
def test_record_created_is_sent_after_commit():
    received = []

    def receiver(sender, record, **kwargs):
        received.append(record.position)

    record_created.connect(receiver)
    try:
        with transaction.atomic():
            register(sale(), invoice())
            assert received == []
        assert received == [1]
    finally:
        record_created.disconnect(receiver)


def test_records_cannot_be_written_from_outside():
    record = register(sale(), invoice())
    with pytest.raises(ImmutableRecord):
        record.save()
    with pytest.raises(ImmutableRecord):
        record.delete()
    with pytest.raises(ImmutableRecord):
        Record.objects.filter(pk=record.pk).update(status=Record.Status.ACCEPTED)
    with pytest.raises(ImmutableRecord):
        Record.objects.all().delete()
    with pytest.raises(ImmutableRecord):
        Record.objects.create(installation=record.installation, position=2)
    with pytest.raises(ImmutableRecord):
        record.installation.save()


def test_related_managers_cannot_move_records():
    record = register(sale("A-1"), invoice("A-1"))
    with pytest.raises(ImmutableRecord):
        sale("A-2").verifactu_records.add(record)
    with pytest.raises(ImmutableRecord):
        record.installation.records.add(record)


def offset(record: Record) -> str:
    return value(record, "sf:FechaHoraHusoGenRegistro")[-6:]


def test_generation_time_ignores_the_active_time_zone():
    madrid = timezone.localtime(timezone.now(), ZoneInfo("Europe/Madrid")).strftime("%z")
    with timezone.override(ZoneInfo("America/Bogota")):
        record = register(sale(), invoice())
    assert offset(record) == f"{madrid[:3]}:{madrid[3:]}"


def test_generation_time_zone_is_configurable(settings):
    settings.VERIFACTU = {**settings.VERIFACTU, "TIME_ZONE": "Atlantic/Canary"}
    canary = timezone.localtime(timezone.now(), ZoneInfo("Atlantic/Canary")).strftime("%z")
    assert offset(register(sale(), invoice())) == f"{canary[:3]}:{canary[3:]}"
