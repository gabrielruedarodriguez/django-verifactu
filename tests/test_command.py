from io import StringIO

import pytest
from django.core.management import call_command

from django_verifactu.management.commands import verifactu_send
from django_verifactu.models import Record
from tests.conftest import registered

pytestmark = pytest.mark.django_db


def run(*args) -> str:
    out = StringIO()
    call_command("verifactu_send", *args, stdout=out)
    return out.getvalue()


def test_one_pass_sends_the_pending_records(aeat):
    registered("A-1", "A-2")
    assert run() == "89890001K: answered, 2 records\n"
    assert set(Record.objects.values_list("status", flat=True)) == {"accepted"}


def test_a_taxpayer_with_problems_does_not_stop_the_others(aeat, settings):
    taxpayers = settings.VERIFACTU["TAXPAYERS"]
    broken = {**taxpayers["89890002E"], "password": "wrong"}
    settings.VERIFACTU = {**settings.VERIFACTU, "TAXPAYERS": {**taxpayers, "89890002E": broken}}
    registered("A-1")
    out = StringIO()
    call_command("verifactu_send", skip_checks=False, stdout=out, stderr=StringIO())
    assert out.getvalue() == "89890001K: answered, 1 records\n"


def test_nothing_pending_prints_nothing(aeat):
    assert run() == ""
    assert aeat.calls == []


def test_one_taxpayer_can_be_sent_alone(aeat):
    registered("A-1")
    registered("B-1", issuer="89890002E")
    assert run("--taxpayer", "89890002E") == "89890002E: answered, 1 records\n"
    assert aeat.calls == [["B-1"]]


def test_the_loop_stops_cleanly_on_a_signal(aeat, monkeypatch):
    handlers, passes = {}, []

    def pause(seconds):
        passes.append(seconds)
        if len(passes) == 2:
            handlers[verifactu_send.signal.SIGTERM](verifactu_send.signal.SIGTERM, None)

    monkeypatch.setattr(verifactu_send.signal, "signal", handlers.__setitem__)
    monkeypatch.setattr(verifactu_send.time, "sleep", pause)
    registered("A-1")
    assert run("--loop", "--interval", "0.5") == "89890001K: answered, 1 records\n"
    assert aeat.calls == [["A-1"]]
    assert set(handlers) == {verifactu_send.signal.SIGTERM, verifactu_send.signal.SIGINT}
