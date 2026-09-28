import threading
import time
from dataclasses import replace
from datetime import date, timedelta

import pytest
from django.db import connection, connections, transaction
from django.utils import timezone
from lxml import etree

from django_verifactu import sending
from django_verifactu.aeat.elements import RECORDS, tag
from django_verifactu.aeat.soap import NotDelivered, OutcomeUnknown, Refused
from django_verifactu.aeat.transport import client_ssl_context
from django_verifactu.issuing import register
from django_verifactu.models import Record, Submission, SubmissionLine
from django_verifactu.sending import send_pending
from django_verifactu.signals import record_answered, submission_finished
from tests.aeat.sample import INVOICE, REJECTION, SOAP, error, response, response_line
from tests.conftest import registered
from tests.shop.models import Sale

pytestmark = pytest.mark.django_db
OTHER = "89890002E"
REAL_NOW = timezone.now


def later(monkeypatch, seconds):
    moment = REAL_NOW() + timedelta(seconds=seconds)
    monkeypatch.setattr(timezone, "now", lambda: moment)


def statuses():
    return [(r.status, r.error_code) for r in Record.objects.order_by("installation", "position")]


def test_pending_records_are_sent_in_chain_order(aeat):
    registered("A-1", "A-2", "A-3")
    [submission] = send_pending()
    assert aeat.calls == [["A-1", "A-2", "A-3"]]
    assert submission.outcome == Submission.Outcome.ANSWERED
    assert (submission.csv, submission.wait_seconds) == ("A-TEST-CSV", 60)
    assert submission.in_flight is None
    assert etree.fromstring(submission.response.encode()) is not None
    assert statuses() == [("accepted", None)] * 3


def test_every_answer_is_stored_with_its_record(aeat):
    aeat.answers = {
        "A-2": ("AceptadoConErrores", error(2001, "NIF no censado")),
        "A-3": ("Incorrecto", REJECTION),
    }
    registered("A-1", "A-2", "A-3")
    send_pending()
    assert statuses() == [("accepted", None), ("accepted_with_errors", 2001), ("rejected", 1100)]
    assert Record.objects.get(invoice_number="A-2").needs_amendment
    lines = SubmissionLine.objects.order_by("record__position")
    assert [line.status for line in lines] == ["Correcto", "AceptadoConErrores", "Incorrecto"]


@pytest.mark.django_db(transaction=True)
def test_the_attempt_is_committed_before_the_aeat_is_called(aeat, monkeypatch):
    seen = []

    def watching(element, **kwargs):
        rows = list(Submission.objects.values_list("outcome", "in_flight"))
        seen.append((connection.in_atomic_block, rows))
        return aeat(element)

    monkeypatch.setattr(sending, "post", watching)
    registered("A-1")
    send_pending()
    assert seen == [(False, [("sending", "T:89890001K")])]


def test_the_aeat_waiting_time_is_respected(aeat, monkeypatch):
    registered("A-1")
    send_pending()
    registered("A-2")
    assert send_pending() == []
    later(monkeypatch, 61)
    assert len(send_pending()) == 1
    assert aeat.calls == [["A-1"], ["A-2"]]


def issuer(element) -> str:
    return element.findtext(f".//{tag(RECORDS, 'NIF')}")


def test_a_refused_certificate_fails_only_its_taxpayer(aeat, monkeypatch):
    def post(element, **kwargs):
        if issuer(element) == OTHER:
            raise Refused("the AEAT refused the certificate (HTTP 302 .../erro4011.html)")
        return aeat(element, **kwargs)

    monkeypatch.setattr(sending, "post", post)
    registered("B-1", issuer=OTHER)
    registered("A-1")
    submissions = send_pending()
    outcomes = {s.installation.taxpayer_tax_id: s.outcome for s in submissions}
    assert outcomes == {OTHER: "fault", "89890001K": "answered"}
    assert "erro4011" in Submission.objects.get(outcome="fault").response
    assert statuses() == [("pending", None), ("accepted", None)]


def test_unusable_credentials_are_a_fault_of_their_taxpayer(aeat, monkeypatch, settings):
    monkeypatch.setattr(sending, "client_ssl_context", client_ssl_context)
    taxpayers = settings.VERIFACTU["TAXPAYERS"]
    wrong = {**taxpayers[OTHER], "password": "wrong"}
    settings.VERIFACTU = {**settings.VERIFACTU, "TAXPAYERS": {**taxpayers, OTHER: wrong}}
    registered("B-1", issuer=OTHER)
    registered("A-1")
    outcomes = {s.installation.taxpayer_tax_id: s.outcome for s in send_pending()}
    assert outcomes == {OTHER: "fault", "89890001K": "answered"}
    settings.VERIFACTU = {**settings.VERIFACTU, "TAXPAYERS": taxpayers}
    later(monkeypatch, 61)
    [resent] = send_pending()
    assert (resent.installation.taxpayer_tax_id, resent.incident) == (OTHER, True)


def test_faults_never_store_the_password(aeat, monkeypatch, settings):
    monkeypatch.setattr(sending, "client_ssl_context", client_ssl_context)
    taxpayers = settings.VERIFACTU["TAXPAYERS"]
    unusable = {**taxpayers["89890001K"], "password": "contrase\udcf1a-SECRET"}
    settings.VERIFACTU = {**settings.VERIFACTU, "TAXPAYERS": {"89890001K": unusable}}
    registered("A-1")
    [submission] = send_pending()
    assert submission.outcome == "fault"
    assert "SECRET" not in submission.response


def test_the_end_of_verifactu_is_declared(aeat, monkeypatch, settings):
    end = date(timezone.now().year, 12, 31)
    taxpayers = settings.VERIFACTU["TAXPAYERS"]
    leaving = {**taxpayers["89890001K"], "verifactu_end_date": end}
    settings.VERIFACTU = {**settings.VERIFACTU, "TAXPAYERS": {**taxpayers, "89890001K": leaving}}
    headers = []

    def post(element, **kwargs):
        headers.append(element.findtext(f".//{tag(RECORDS, 'FechaFinVeriFactu')}"))
        return aeat(element, **kwargs)

    monkeypatch.setattr(sending, "post", post)
    registered("A-1")
    send_pending()
    assert headers == [f"31-12-{end.year}"]


def test_each_taxpayer_is_sent_on_its_own(aeat):
    registered("A-1")
    registered("B-1", issuer=OTHER)
    assert len(send_pending()) == 2
    assert aeat.calls == [["A-1"], ["B-1"]]
    assert statuses() == [("accepted", None)] * 2


def test_only_one_sender_works_for_a_taxpayer_at_a_time(aeat, monkeypatch):
    nested = []

    def busy(element, **kwargs):
        nested.append(send_pending())
        return aeat(element)

    monkeypatch.setattr(sending, "post", busy)
    registered("A-1")
    send_pending()
    assert nested == [[]]


@pytest.mark.parametrize(
    ("failure", "outcome"),
    [(NotDelivered("down"), "not_delivered"), (OutcomeUnknown("lost"), "unknown")],
)
def test_failed_deliveries_keep_the_records_pending(aeat, failure, outcome):
    aeat.failure = failure
    registered("A-1")
    [submission] = send_pending()
    assert (submission.outcome, submission.in_flight) == (outcome, None)
    assert statuses() == [("pending", None)]


def test_faults_are_stored_with_their_code(aeat):
    aeat.content = f"""<env:Envelope xmlns:env="{SOAP}"><env:Body><env:Fault>
<faultcode>env:Client</faultcode><faultstring>Codigo[4102].Falta un campo</faultstring>
</env:Fault></env:Body></env:Envelope>""".encode()
    registered("A-1")
    [submission] = send_pending()
    assert (submission.outcome, submission.error_code) == ("fault", 4102)
    assert statuses() == [("pending", None)]


def test_failed_attempts_are_retried_after_a_pause(aeat, monkeypatch):
    aeat.failure = NotDelivered("down")
    registered("A-1")
    send_pending()
    aeat.failure = None
    assert send_pending() == []
    later(monkeypatch, 61)
    [submission] = send_pending()
    assert submission.outcome == "answered"


def test_answers_are_announced_after_they_are_stored(aeat):
    answered, finished = [], []

    def on_answer(sender, record, line, **kwargs):
        answered.append((record.invoice_number, line.status))

    def on_finish(sender, submission, **kwargs):
        finished.append(submission.outcome)

    record_answered.connect(on_answer)
    submission_finished.connect(on_finish)
    try:
        registered("A-1")
        send_pending()
    finally:
        record_answered.disconnect(on_answer)
        submission_finished.disconnect(on_finish)
    assert (answered, finished) == ([("A-1", "Correcto")], ["answered"])


@pytest.mark.django_db(transaction=True)
def test_sending_runs_outside_transactions(aeat):
    registered("A-1")
    with transaction.atomic(), pytest.raises(RuntimeError):
        send_pending()


@pytest.mark.django_db(transaction=True)
def test_sending_never_waits_for_an_open_issuer(aeat):
    if connection.vendor != "postgresql":
        pytest.skip("set VERIFACTU_TEST_POSTGRES to run it against PostgreSQL")
    registered("A-1")
    locked, release = threading.Event(), threading.Event()

    def issuer():
        try:
            with transaction.atomic():
                register(Sale.objects.create(number="A-2"), replace(INVOICE, invoice_number="A-2"))
                locked.set()
                release.wait(10)
        finally:
            connections.close_all()

    thread = threading.Thread(target=issuer)
    thread.start()
    assert locked.wait(10)
    started = time.monotonic()
    try:
        [submission] = send_pending()
    finally:
        release.set()
        thread.join()
    assert time.monotonic() - started < 5
    assert submission.outcome == "answered"


def test_the_aeat_waiting_time_also_applies_after_a_failure(aeat, monkeypatch):
    aeat.content = response("Correcto", response_line("Correcto", invoice_number="A-1")).replace(
        b"<tikR:TiempoEsperaEnvio>60<", b"<tikR:TiempoEsperaEnvio>300<"
    )
    registered("A-1")
    send_pending()
    aeat.content, aeat.failure = None, OutcomeUnknown("lost")
    later(monkeypatch, 301)
    registered("A-2")
    send_pending()
    aeat.failure = None
    later(monkeypatch, 301 + 61)
    assert send_pending() == []
    later(monkeypatch, 301 + 301)
    assert len(send_pending()) == 1


def test_the_oldest_pending_record_goes_first(aeat, monkeypatch):
    registered("A-1", "A-2")
    send_pending()
    later(monkeypatch, 61)
    registered("B-1", issuer=OTHER)
    later(monkeypatch, 62)
    registered("A-3")
    later(monkeypatch, 63)
    send_pending()
    assert aeat.calls[-2:] == [["B-1"], ["A-3"]]


def test_an_answer_for_another_invoice_leaves_the_record_pending(aeat, monkeypatch):
    def confused(element, **kwargs):
        aeat(element)
        return response("Correcto", response_line("Correcto", invoice_number="A-9"))

    monkeypatch.setattr(sending, "post", confused)
    registered("A-1")
    [submission] = send_pending()
    assert submission.outcome == "answered"
    assert statuses() == [("pending", None)]
    assert SubmissionLine.objects.get().status is None
