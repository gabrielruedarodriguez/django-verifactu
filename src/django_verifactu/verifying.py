from collections import defaultdict
from collections.abc import Iterator
from datetime import date, timedelta

from django.db import router
from django.db.models import Max, Min
from django.utils import timezone
from lxml import etree

from django_verifactu import conf
from django_verifactu.aeat.codes import Operation
from django_verifactu.aeat.domain import StoredRecord
from django_verifactu.aeat.elements import RECORDS, tag
from django_verifactu.aeat.formatting import format_date
from django_verifactu.aeat.records import fingerprint_of
from django_verifactu.models import Installation, Record
from django_verifactu.querying import query

_STORED = {Record.Status.ACCEPTED, Record.Status.ACCEPTED_WITH_ERRORS}
_CLOCK_MARGIN = timedelta(minutes=1)
_BATCH = 1000


# Problems found in this environment's chains and, with aeat=True, against what the AEAT holds.
def verify(*, taxpayer_tax_id: str | None = None, aeat: bool = False) -> list[str]:
    # Where issuing and sending write: a lagging replica would miss what the AEAT already holds.
    using = router.db_for_write(Record)
    installations = Installation.objects.using(using).filter(production=conf.production())
    if taxpayer_tax_id is not None:
        installations = installations.filter(taxpayer_tax_id=taxpayer_tax_id)
    installations = list(installations.order_by("taxpayer_tax_id", "generation"))
    problems = []
    for installation in installations:
        problems += chain_problems(installation, using)
    if aeat:
        for tax_id in dict.fromkeys(i.taxpayer_tax_id for i in installations):
            numbers = {i.number for i in installations if i.taxpayer_tax_id == tax_id}
            problems += _verify_at_aeat(tax_id, numbers, using)
    return problems


# The records after position `after`, each checked against the one before it.
def chain_problems(installation: Installation, using: str, *, after: int = -1) -> list[str]:
    records = installation.records.using(using)
    previous = records.filter(position=after).defer("xml").first() if after > 0 else None
    expected = max(after, 0) + 1
    problems = []
    for record in _in_order(installation, using, after):
        problems += record_problems(installation, record, previous, expected)
        previous, expected = record, record.position + 1
    return problems


# Orden HAC/1177/2024, art. 7.i: correctly chained, and never dated a minute before the last.
def record_problems(
    installation: Installation, record: Record, previous: Record | None, expected: int
) -> list[str]:
    where = f"{installation} #{record.position} ({record})"
    problems = []
    if record.position != expected:
        problems.append(f"{where}: the chain should continue with #{expected}")
    if previous and record.generated_at < previous.generated_at - _CLOCK_MARGIN:
        problems.append(f"{where}: it was generated more than a minute before the record before it")
    try:
        element = etree.fromstring(record.xml)
    except (etree.XMLSyntaxError, ValueError):
        return [*problems, f"{where}: its XML cannot be read"]
    if not fingerprint_of(element) == _text(element, "Huella") == record.fingerprint:
        problems.append(f"{where}: its XML or its fingerprint was altered")
    columns = (
        record.operation,
        installation.taxpayer_tax_id,
        record.invoice_number,
        format_date(record.issue_date),
        record.amendment,
    )
    if _identity(element) != columns:
        problems.append(f"{where}: its columns do not match its XML")
    if _link(element) != _link_to(installation, previous):
        problems.append(f"{where}: it does not follow the record before it")
    return problems


# The AEAT holds, per invoice, the last record it accepted (verified live).
def _verify_at_aeat(tax_id: str, numbers: set[str], using: str) -> list[str]:
    records = Record.objects.using(using).filter(
        installation__production=conf.production(), installation__taxpayer_tax_id=tax_id
    )
    bounds = records.aggregate(first=Min("issue_date"), last=Max("issue_date"))
    if bounds["first"] is None:
        return []
    # Cancellations may carry future issue dates, and the AEAT accepts them.
    last = max(bounds["last"], timezone.localtime(timezone.now(), conf.time_zone()).date())
    problems = []
    for month in _months(bounds["first"], last):
        following = (month + timedelta(days=32)).replace(day=1)
        issued = records.filter(issue_date__gte=month, issue_date__lt=following).defer("xml")
        issued = issued.order_by("installation__generation", "position")
        before = _histories(issued)
        try:
            held = _held(tax_id, month)
            keys = before.keys() | {key for key, stored in held.items() if _ours(stored, numbers)}
            suspects = [
                k for k in sorted(keys) if _compare(before[k], before[k], held.get(k), numbers)
            ]
            for number, issue_date in suspects:
                # A record presented meanwhile moves its invoice to a page already read.
                if (number, issue_date) not in held:
                    held |= _held(tax_id, month, invoice_number=number, issue_date=issue_date)
        except Exception as error:
            failure = f"the AEAT could not be queried for {month:%m-%Y}: {type(error).__name__}"
            return [*problems, f"{tax_id}: {failure}: {error}"]
        # Read again: whatever the AEAT holds was committed here before it was sent.
        after = _histories(issued.all()) if suspects else before
        for number, issue_date in suspects:
            key = number, issue_date
            if problem := _compare(before[key], after[key], held.get(key), numbers):
                problems.append(f"{tax_id} {number} {issue_date:%d-%m-%Y}: {problem}")
    return problems


def _held(tax_id: str, month: date, **filters) -> dict[tuple, StoredRecord]:
    found = query(tax_id, year=month.year, month=month.month, show_software=True, **filters)
    return {(r.invoice.invoice_number, r.invoice.issue_date): r for r in found}


def _compare(
    before: list[Record], after: list[Record], stored: StoredRecord | None, numbers: set[str]
) -> str | None:
    if stored is None:
        latest = _latest(after)
        return f"the AEAT does not hold #{latest.position}" if latest else None
    if stored.fingerprint in _expected(before) | _expected(after):
        return None
    if not after:
        ours = _ours(stored, numbers)
        return "the AEAT holds it from this system, but the database does not" if ours else None
    latest = _latest(after)
    instead = f" instead of #{latest.position}" if latest else ""
    known = {record.fingerprint: record for record in after}
    if (record := known.get(stored.fingerprint)) is not None:
        return f"the AEAT holds #{record.position}, {record.status} here{instead}"
    if _ours(stored, numbers):
        return f"the AEAT holds a record of this system the database does not have{instead}"
    if latest is not None:
        return f"the AEAT holds another system's record{instead}"
    return None


def _histories(records) -> defaultdict[tuple, list[Record]]:
    histories = defaultdict(list)
    for record in records:
        histories[record.invoice_number, record.issue_date].append(record)
    return histories


def _latest(history: list[Record]) -> Record | None:
    answered = [record for record in history if record.status in _STORED]
    return answered[-1] if answered else None


# The last record the AEAT accepted, or a pending one that may have reached it already.
def _expected(history: list[Record]) -> set[str]:
    latest = _latest(history)
    later = history[history.index(latest) + 1 :] if latest else history
    pending = {r.fingerprint for r in later if r.status == Record.Status.PENDING}
    return pending | {latest.fingerprint} if latest else pending


# Paged by position: iterator() would hold a whole chain in memory on MySQL.
def _in_order(installation: Installation, using: str, after: int) -> Iterator[Record]:
    records = installation.records.using(using).order_by("position")
    # From -1 by default, so a record moved to #0 is checked too.
    position = after
    while batch := list(records.filter(position__gt=position)[:_BATCH]):
        yield from batch
        if len(batch) < _BATCH:
            return
        position = batch[-1].position


def _ours(stored: StoredRecord, numbers: set[str]) -> bool:
    return stored.software is not None and stored.software.installation_number in numbers


def _months(first: date, last: date) -> Iterator[date]:
    month = first.replace(day=1)
    while month <= last:
        yield month
        month = (month + timedelta(days=32)).replace(day=1)


def _text(element: etree._Element, path: str) -> str | None:
    return element.findtext("/".join(tag(RECORDS, name) for name in path.split("/")))


def _identity(element: etree._Element) -> tuple:
    cancellation = element.tag == tag(RECORDS, "RegistroAnulacion")
    suffix = "Anulada" if cancellation else ""
    return (
        Operation.CANCELLATION if cancellation else Operation.REGISTRATION,
        _text(element, f"IDFactura/IDEmisorFactura{suffix}"),
        _text(element, f"IDFactura/NumSerieFactura{suffix}"),
        _text(element, f"IDFactura/FechaExpedicionFactura{suffix}"),
        _text(element, "Subsanacion") == "S",
    )


def _link(element: etree._Element) -> tuple | None:
    if _text(element, "Encadenamiento/PrimerRegistro") == "S":
        return None
    names = ("IDEmisorFactura", "NumSerieFactura", "FechaExpedicionFactura", "Huella")
    return tuple(_text(element, f"Encadenamiento/RegistroAnterior/{name}") for name in names)


def _link_to(installation: Installation, previous: Record | None) -> tuple | None:
    if previous is None:
        return None
    return (
        installation.taxpayer_tax_id,
        previous.invoice_number,
        format_date(previous.issue_date),
        previous.fingerprint,
    )
