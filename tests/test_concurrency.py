import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from django.db import connection, connections, transaction
from lxml import etree

from django_verifactu.aeat.codes import RecordStatus
from django_verifactu.aeat.domain import Invoice, Party
from django_verifactu.issuing import new_installation, register
from django_verifactu.models import Installation, Record
from tests.aeat.live import now, requires_aeat, submit, taxpayer
from tests.aeat.sample import INVOICE
from tests.shop.models import Sale

WORKERS, EACH = 8, 25

pytestmark = pytest.mark.django_db(transaction=True)


def issue_concurrently(template: Invoice) -> list[Record]:
    if connection.vendor != "postgresql":
        pytest.skip("set VERIFACTU_TEST_POSTGRES to run it against PostgreSQL")

    def issue(worker: int) -> None:
        try:
            for index in range(EACH):
                number = f"{template.invoice_number}-{worker}-{index}"
                with transaction.atomic():
                    sale = Sale.objects.create(number=number)
                    register(sale, replace(template, invoice_number=number))
        finally:
            connections.close_all()

    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(issue, range(WORKERS)))
    return list(Record.objects.order_by("position"))


def previous_fingerprint(record: Record) -> str | None:
    element = etree.fromstring(record.xml)
    path = "sf:Encadenamiento/sf:RegistroAnterior/sf:Huella"
    return element.findtext(path, namespaces={"sf": element.nsmap["sum1"]})


def test_concurrent_issuers_keep_one_linear_chain():
    records = issue_concurrently(replace(INVOICE, invoice_number="C"))

    assert Installation.objects.count() == 1
    assert [record.position for record in records] == list(range(1, WORKERS * EACH + 1))
    assert previous_fingerprint(records[0]) is None
    for previous, record in zip(records, records[1:]):
        assert previous_fingerprint(record) == previous.fingerprint
        assert record.generated_at >= previous.generated_at


def test_an_issuer_waiting_for_a_new_installation_moves_to_it():
    if connection.vendor != "postgresql":
        pytest.skip("set VERIFACTU_TEST_POSTGRES to run it against PostgreSQL")
    with transaction.atomic():
        register(Sale.objects.create(number="A-1"), replace(INVOICE, invoice_number="A-1"))
    locked, release = threading.Event(), threading.Event()

    def restart() -> Installation:
        try:
            with transaction.atomic():
                installation = new_installation(INVOICE.issuer_tax_id)
                locked.set()
                release.wait(10)
            return installation
        finally:
            connections.close_all()

    def issue() -> Record:
        locked.wait(10)
        try:
            with transaction.atomic():
                sale = Sale.objects.create(number="A-2")
                return register(sale, replace(INVOICE, invoice_number="A-2"))
        finally:
            connections.close_all()

    with ThreadPoolExecutor(2) as pool:
        restarted, issued = pool.submit(restart), pool.submit(issue)
        waiting = "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'"
        with connection.cursor() as cursor:
            for _ in range(100):
                cursor.execute(waiting)
                if cursor.fetchone()[0]:
                    break
                time.sleep(0.05)
        release.set()
        assert issued.result().installation == restarted.result()


@requires_aeat
def test_a_chain_built_concurrently_is_accepted_by_the_aeat(settings):
    company, moment = taxpayer(), now()
    owner = Party(company.name, tax_id=company.tax_id)
    software = {**settings.VERIFACTU["SOFTWARE"], "producer": owner}
    settings.VERIFACTU = {**settings.VERIFACTU, "SOFTWARE": software}
    template = replace(
        INVOICE,
        issuer_tax_id=company.tax_id,
        issuer_name=company.name,
        invoice_number=f"CC-{moment:%Y%m%d%H%M%S}",
        issue_date=moment.date(),
        recipients=(owner,),
    )
    records = issue_concurrently(template)

    result = submit(company, [etree.fromstring(record.xml) for record in records])

    assert {line.status for line in result.records} == {RecordStatus.ACCEPTED}
    assert len(result.records) == WORKERS * EACH
