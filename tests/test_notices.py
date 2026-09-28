from dataclasses import replace
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.db import transaction
from django.template import Context, Template
from django.urls import reverse
from django.utils import timezone

from django_verifactu.aeat.soap import NotDelivered
from django_verifactu.issuing import register
from django_verifactu.models import Record
from django_verifactu.notices import notices
from django_verifactu.sending import send_pending
from django_verifactu.signals import alarm_raised
from tests.aeat.sample import INVOICE
from tests.conftest import registered
from tests.shop.models import Sale

pytestmark = pytest.mark.django_db
REAL_NOW = timezone.now


def later(monkeypatch, seconds):
    moment = REAL_NOW() + timedelta(seconds=seconds)
    monkeypatch.setattr(timezone, "now", lambda: moment)


def tamper(record, **fields):
    Record._writes.filter(pk=record.pk).update(**fields)


def messages():
    return [notice.message for notice in notices()]


def test_nothing_to_warn_about_while_records_go_out(aeat):
    registered("A-1")
    assert notices() == []
    send_pending()
    assert notices() == []


def test_unsent_records_are_counted_from_a_failed_submission_until_all_are_sent(aeat, monkeypatch):
    registered("A-1", "A-2")
    aeat.failure = NotDelivered("down")
    send_pending()
    registered("A-3")
    [notice] = notices()
    assert notice.taxpayer_tax_id == "89890001K"
    assert "3 VERI*FACTU records of 89890001K could not be sent" in notice.message
    aeat.failure = None
    later(monkeypatch, 61)
    send_pending()
    assert notices() == []


def test_records_waiting_longer_than_the_aeat_tolerates_are_an_incident(monkeypatch):
    registered("A-1")
    later(monkeypatch, 241)
    assert messages() == ["1 VERI*FACTU records of 89890001K could not be sent to the AEAT yet"]


def test_each_taxpayer_gets_its_own_notices(aeat):
    registered("B-1", issuer="89890002E")
    registered("A-1")
    aeat.failure = NotDelivered("down")
    send_pending(taxpayer_tax_id="89890002E")
    assert [n.taxpayer_tax_id for n in notices(taxpayer_tax_id="89890002E")] == ["89890002E"]
    assert notices(taxpayer_tax_id="89890001K") == []


def test_a_broken_chain_among_the_latest_records_is_a_notice():
    first, _ = registered("A-1", "A-2")
    tamper(first, fingerprint="0" * 64)
    found = messages()
    assert len(found) == 2 and all("chain" in message for message in found)


@pytest.mark.django_db(transaction=True)
def test_a_sound_chain_raises_no_alarm(caplog):
    raised = []

    def receiver(sender, installation, problems, **kwargs):
        raised.append(problems)

    alarm_raised.connect(receiver)
    try:
        registered("A-1", "A-2", "A-3")
    finally:
        alarm_raised.disconnect(receiver)
    assert raised == [] and "chain problem" not in caplog.text


@pytest.mark.django_db(transaction=True)
def test_issuing_after_a_broken_record_raises_an_alarm_and_still_issues(caplog):
    [first] = registered("A-1")
    tamper(first, fingerprint="0" * 64)
    raised = []

    def receiver(sender, installation, problems, **kwargs):
        raised.append(problems)

    alarm_raised.connect(receiver)
    try:
        [second] = registered("A-2")
    finally:
        alarm_raised.disconnect(receiver)
    assert second.position == 2
    assert len(raised) == 1 and "altered" in raised[0][0]
    assert "altered" in caplog.text


@pytest.mark.django_db(transaction=True)
def test_the_alarm_waits_for_the_commit_and_is_dropped_with_a_rollback():
    [first] = registered("A-1")
    tamper(first, fingerprint="0" * 64)
    raised = []

    def receiver(sender, installation, problems, **kwargs):
        raised.append(problems)

    alarm_raised.connect(receiver)
    try:
        with pytest.raises(RuntimeError), transaction.atomic():
            register(Sale.objects.create(number="A-2"), replace(INVOICE, invoice_number="A-2"))
            assert raised == []
            raise RuntimeError
        assert raised == []
        with transaction.atomic():
            register(Sale.objects.create(number="A-2"), replace(INVOICE, invoice_number="A-2"))
            assert raised == []
        assert len(raised) == 1
    finally:
        alarm_raised.disconnect(receiver)


def test_only_the_latest_records_are_looked_at():
    records = registered(*(f"A-{n}" for n in range(1, 26)))
    assert notices() == []
    tamper(records[4], fingerprint="0" * 64)
    [notice] = notices()
    assert "#6" in notice.message and "follow" in notice.message
    tamper(records[3], fingerprint="0" * 64)
    assert len(notices()) == 1


def test_notices_cost_a_few_queries_per_taxpayer(django_assert_max_num_queries, aeat):
    registered("A-1", "A-2")
    registered("B-1", issuer="89890002E")
    aeat.failure = NotDelivered("down")
    send_pending()
    with django_assert_max_num_queries(8):
        notices()


@pytest.mark.django_db(transaction=True)
def test_a_clock_that_went_back_raises_an_alarm(monkeypatch):
    registered("A-1")
    later(monkeypatch, -120)
    raised = []

    def receiver(sender, installation, problems, **kwargs):
        raised.append(problems)

    alarm_raised.connect(receiver)
    try:
        registered("A-2")
    finally:
        alarm_raised.disconnect(receiver)
    assert "more than a minute after" in raised[0][0]


def test_the_template_tag_shows_the_notices(monkeypatch):
    registered("A-1")
    later(monkeypatch, 241)
    html = Template("{% load verifactu %}{% verifactu_notices %}").render(Context())
    assert "1 VERI*FACTU records of 89890001K could not be sent" in html
    html = Template('{% load verifactu %}{% verifactu_notices "89890002E" %}').render(Context())
    assert "VERI*FACTU" not in html


@pytest.mark.parametrize("nif", [None, ""])
def test_a_missing_nif_shows_no_one_else_s_notices(monkeypatch, nif):
    registered("A-1")
    later(monkeypatch, 241)
    html = Template("{% load verifactu %}{% verifactu_notices nif %}").render(Context({"nif": nif}))
    assert "VERI*FACTU" not in html


def test_the_admin_shows_the_notices(admin_client, monkeypatch):
    registered("A-1")
    later(monkeypatch, 241)
    page = admin_client.get(reverse("admin:django_verifactu_record_changelist"))
    assert "could not be sent to the AEAT yet" in page.content.decode()


def test_the_admin_shows_no_notices_to_whom_cannot_see_the_records(client, monkeypatch):
    staff = User.objects.create_user("staff", password="x", is_staff=True)
    client.force_login(staff)
    registered("A-1")
    later(monkeypatch, 241)
    assert client.get(reverse("admin:django_verifactu_record_changelist")).status_code == 403
    assert "could not be sent" not in client.get(reverse("admin:index")).content.decode()
