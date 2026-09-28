from dataclasses import replace
from datetime import date, timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import transaction

from django_verifactu import querying, verifying
from django_verifactu.aeat.domain import InvoiceId, QueryPage
from django_verifactu.issuing import amend, cancel, register
from django_verifactu.models import Record
from django_verifactu.querying import query
from django_verifactu.verifying import verify
from tests.aeat.sample import CANCELLATION, INVOICE
from tests.conftest import registered, stored
from tests.shop.models import Sale

pytestmark = pytest.mark.django_db


def tamper(record, **fields):
    Record._writes.filter(pk=record.pk).update(**fields)


def accepted(*records):
    Record._writes.filter(pk__in=[r.pk for r in records]).update(status="accepted")
    return [Record.objects.get(pk=r.pk) for r in records]


@pytest.fixture
def held(monkeypatch):
    records = []

    def query(tax_id, *, year, month, show_software, invoice_number=None, issue_date=None):
        assert show_software
        return [
            r
            for r in records
            if r.invoice.issuer_tax_id == tax_id
            and (r.invoice.issue_date.year, r.invoice.issue_date.month) == (year, month)
            and invoice_number in (None, r.invoice.invoice_number)
            and issue_date in (None, r.invoice.issue_date)
        ]

    monkeypatch.setattr(verifying, "query", query)
    return records


def test_query_follows_every_page(monkeypatch):
    first, second = accepted(*registered("A-1", "A-2"))
    pages = [QueryPage((stored(first),), InvoiceId("89890001K", "A-1", INVOICE.issue_date))]
    pages.append(QueryPage((stored(second),), None))
    keys = []

    def send_query(element, **kwargs):
        keys.append(element.findtext(".//{*}ClavePaginacion/{*}NumSerieFactura"))
        return pages[len(keys) - 1]

    monkeypatch.setattr(querying, "send_query", send_query)
    monkeypatch.setattr(querying, "client_ssl_context", lambda *args: None)
    found = query("89890001K", year=2026, month=9)
    assert [r.invoice.invoice_number for r in found] == ["A-1", "A-2"]
    assert keys == [None, "A-1"]


def test_an_intact_chain_has_no_problems():
    registered("A-1", "A-2")
    with transaction.atomic():
        obj = Sale.objects.create(number="A-3")
        register(obj, INVOICE)
        cancel(obj, CANCELLATION)
    assert verify() == []


def test_an_altered_xml_is_detected():
    first, _ = registered("A-1", "A-2")
    tamper(first, xml=first.xml.replace("<sum1:ImporteTotal>121.00", "<sum1:ImporteTotal>1.00"))
    [problem] = verify()
    assert "#1" in problem and "altered" in problem


def test_an_altered_fingerprint_breaks_the_chain():
    first, _ = registered("A-1", "A-2")
    tamper(first, fingerprint="0" * 64)
    problems = verify()
    assert ["#1" in problems[0], "#2" in problems[1]] == [True, True]
    assert "altered" in problems[0] and "follow" in problems[1]


def test_an_unreadable_xml_is_reported_and_the_rest_still_checked():
    first, second = registered("A-1", "A-2")
    tamper(first, xml=first.xml[:-20])
    tamper(second, invoice_number="A-9")
    problems = verify()
    assert "#1" in problems[0] and "cannot be read" in problems[0]
    assert "#2" in problems[1] and "columns" in problems[1]


def test_a_record_dated_before_the_one_before_it_is_detected():
    first, second = registered("A-1", "A-2")
    tamper(second, generated_at=first.generated_at - timedelta(minutes=2))
    [problem] = verify()
    assert "#2" in problem and "more than a minute before" in problem


def test_columns_that_disagree_with_the_xml_are_detected():
    [first] = registered("A-1")
    tamper(first, invoice_number="A-9")
    [problem] = verify()
    assert "columns" in problem


def test_missing_records_are_detected():
    _, second, _ = registered("A-1", "A-2", "A-3")
    Record._writes.filter(pk=second.pk).delete()
    problems = verify()
    assert "#3" in problems[0] and "should continue with #2" in problems[0]
    assert "#3" in problems[1] and "follow" in problems[1]


def test_a_record_moved_out_of_the_chain_is_still_checked():
    [first] = registered("A-1")
    tamper(first, position=0, xml="garbage")
    problems = verify()
    assert "should continue with #1" in problems[0] and "cannot be read" in problems[1]


def test_each_taxpayer_can_be_verified_alone():
    [first] = registered("A-1")
    registered("B-1", issuer="89890002E")
    tamper(first, invoice_number="A-9")
    assert verify(taxpayer_tax_id="89890002E") == []


def test_the_aeat_holds_what_was_accepted(held):
    records = accepted(*registered("A-1", "A-2"))
    held.extend(stored(record) for record in records)
    assert verify(aeat=True) == []


def test_an_accepted_record_missing_at_the_aeat_is_detected(held):
    accepted(*registered("A-1"))
    [problem] = verify(aeat=True)
    assert "A-1" in problem and "does not hold" in problem


def test_a_different_record_of_this_system_at_the_aeat_is_detected(held):
    [record] = accepted(*registered("A-1"))
    held.append(stored(record, fingerprint="F" * 64))
    [problem] = verify(aeat=True)
    assert "A-1" in problem and "this system" in problem


def test_another_system_s_record_at_the_aeat_is_detected(held):
    [record] = accepted(*registered("A-1"))
    held.append(stored(record, fingerprint="F" * 64, installation_number="ELSEWHERE"))
    [problem] = verify(aeat=True)
    assert "A-1" in problem and "another system" in problem


def test_records_of_this_system_the_database_lost_are_detected(held):
    first, second = accepted(*registered("A-1", "A-2"))
    held.append(stored(first))
    held.append(stored(second))
    Record._writes.filter(pk=second.pk).delete()
    [problem] = verify(aeat=True)
    assert "A-2" in problem and "database" in problem


def test_invoices_of_other_systems_are_not_ours_to_verify(held):
    [record] = accepted(*registered("A-1"))
    held.append(stored(record))
    [other] = registered("B-1")
    held.append(stored(other, installation_number="ELSEWHERE"))
    Record._writes.filter(pk=other.pk).delete()
    assert verify(aeat=True) == []


def test_pending_records_may_already_be_at_the_aeat(held):
    first, second = accepted(*registered("A-1", "A-2"))
    with transaction.atomic():
        pending = cancel(second.content_object, replace(CANCELLATION, invoice_number="A-2"))
    held.extend([stored(first), stored(pending)])
    assert verify(aeat=True) == []


def test_the_aeat_holding_a_record_the_database_does_not_expect_is_detected(held):
    [first] = accepted(*registered("A-1"))
    with transaction.atomic():
        amended = amend(first.content_object, replace(INVOICE, invoice_number="A-1"))
    accepted(amended)
    held.append(stored(first))
    [problem] = verify(aeat=True)
    assert "holds #1, accepted here instead of #2" in problem


def test_the_aeat_holding_a_record_rejected_here_is_detected(held):
    [record] = registered("A-1")
    tamper(record, status="rejected", error_code=3000)
    held.append(stored(record))
    [problem] = verify(aeat=True)
    assert "holds #1, rejected here" in problem


def test_each_issue_month_is_compared_on_its_own(held, monkeypatch):
    august, september = date(2026, 8, 31), date(2026, 9, 1)
    with transaction.atomic():
        for number, issue_date in [("A-1", august), ("A-2", september)]:
            invoice = replace(INVOICE, invoice_number=number, issue_date=issue_date)
            register(Sale.objects.create(number=number), invoice)
    first, second = accepted(*Record.objects.order_by("position"))
    held.extend([stored(first), stored(second)])
    assert verify(aeat=True) == []
    held.pop(0)
    [problem] = verify(aeat=True)
    assert "A-1 31-08-2026" in problem and "does not hold" in problem


def test_records_issued_while_the_aeat_answers_are_not_problems(held, monkeypatch):
    [first] = accepted(*registered("A-1"))
    held.append(stored(first))
    answer = verifying.query

    def query(tax_id, **options):
        with transaction.atomic():
            invoice = replace(INVOICE, invoice_number="A-2")
            [late] = accepted(register(Sale.objects.create(number="A-2"), invoice))
            amended = amend(first.content_object, replace(INVOICE, invoice_number="A-1"))
        accepted(amended)
        return [*answer(tax_id, **options), stored(late), stored(amended)]

    monkeypatch.setattr(verifying, "query", query)
    assert verify(aeat=True) == []


def test_an_invoice_that_moved_while_the_aeat_answered_is_asked_for_again(held, monkeypatch):
    [first] = accepted(*registered("A-1"))
    with transaction.atomic():
        pending = amend(first.content_object, replace(INVOICE, invoice_number="A-1"))
    held.append(stored(pending))
    answer = verifying.query

    def query(tax_id, **options):
        # The bulk answer was read before the amendment reached the AEAT and moved the invoice.
        return answer(tax_id, **options) if "invoice_number" in options else []

    monkeypatch.setattr(verifying, "query", query)
    assert verify(aeat=True) == []


def test_future_issue_months_are_compared_too(held):
    with transaction.atomic():
        future = replace(CANCELLATION, invoice_number="A-1", issue_date=date(2099, 1, 1))
        [record] = accepted(cancel(Sale.objects.create(number="A-1"), future))
    held.append(stored(record, fingerprint="F" * 64, installation_number="ELSEWHERE"))
    [problem] = verify(aeat=True)
    assert "A-1 01-01-2099" in problem and "another system" in problem


def test_an_unreachable_aeat_is_a_problem(held, monkeypatch, settings):
    accepted(*registered("A-1"))
    settings.VERIFACTU = {**settings.VERIFACTU, "TAXPAYERS": {}}
    monkeypatch.setattr(verifying, "query", querying.query)
    [problem] = verify(aeat=True)
    assert "could not be queried" in problem


def test_the_command_reports_problems():
    [first] = registered("A-1")
    out = StringIO()
    call_command("verifactu_verify", stdout=out)
    assert out.getvalue() == "no problems found\n"
    tamper(first, invoice_number="A-9")
    with pytest.raises(CommandError, match="1 problems"):
        call_command("verifactu_verify", stdout=StringIO())
