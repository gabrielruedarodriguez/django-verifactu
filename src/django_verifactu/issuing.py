import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from operator import attrgetter
from uuid import uuid4

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, models, router, transaction
from django.db.transaction import TransactionManagementError
from django.utils import timezone
from lxml import etree

from django_verifactu import conf
from django_verifactu.aeat.codes import Operation
from django_verifactu.aeat.domain import Cancellation, Invoice, PreviousRecord
from django_verifactu.aeat.elements import RECORDS, tag
from django_verifactu.aeat.identifiers import is_valid_nif
from django_verifactu.aeat.records import build_cancellation_record, build_registration_record
from django_verifactu.aeat.validation import validate_cancellation, validate_invoice
from django_verifactu.aeat.violations import ValidationError
from django_verifactu.lifecycle import (
    AlreadyCancelled,
    AlreadyRegistered,
    LifecycleError,
    NotRegistered,
    Step,
    cancellation_flags,
    registration_flags,
)
from django_verifactu.models import Installation, Record, VerifactuRecords
from django_verifactu.signals import alarm_raised, record_created
from django_verifactu.verifying import record_problems

logger = logging.getLogger("django_verifactu")

__all__ = [
    "AlreadyCancelled",
    "AlreadyRegistered",
    "LifecycleError",
    "NotRegistered",
    "amend",
    "cancel",
    "new_installation",
    "register",
]

_OUR_FLAGS = "django_verifactu decides the lifecycle flags itself"


def register(obj: models.Model, invoice: Invoice) -> Record:
    return _issue_invoice(obj, invoice, amend=False)


def amend(obj: models.Model, invoice: Invoice) -> Record:
    return _issue_invoice(obj, invoice, amend=True)


def cancel(obj: models.Model, cancellation: Cancellation) -> Record:
    if cancellation.without_previous_record or cancellation.previous_rejection:
        raise ValueError(_OUR_FLAGS)
    using = _database(obj)
    if violations := validate_cancellation(cancellation):
        raise ValidationError(violations)
    return _issue(obj, cancellation, cancellation_flags, using)


def _issue_invoice(obj: models.Model, invoice: Invoice, *, amend: bool) -> Record:
    if invoice.amendment or invoice.previous_rejection is not None:
        raise ValueError(_OUR_FLAGS)
    using = _database(obj)
    today = timezone.localtime(timezone.now(), conf.time_zone()).date()
    if violations := validate_invoice(invoice, today):
        raise ValidationError(violations)
    return _issue(obj, invoice, lambda history: registration_flags(history, amend=amend), using)


def _issue(
    obj: models.Model,
    document: Invoice | Cancellation,
    flags: Callable[[list[Step]], dict],
    using: str,
) -> Record:
    registration = isinstance(document, Invoice)
    with transaction.atomic(using=using):
        installation = _installation(document.issuer_tax_id, using)
        history = _history(installation, document.invoice_number, document.issue_date, using)
        steps = [Step(r.operation, r.amendment, r.status, r.error_code) for r in history]
        document = replace(document, **flags(steps))
        _check_owner(obj, installation, document, history, using)
        head = installation.records.using(using).order_by("-position").first()
        # Taken under the lock, so the chain follows the order in which records were generated.
        generated_at = timezone.localtime(timezone.now(), conf.time_zone()).replace(microsecond=0)
        if head is not None:
            _check_head(installation, head, generated_at, using)
        chain = {
            "software": conf.software(
                installation.number, _multiple_taxpayers(installation, using)
            ),
            "previous": _previous(installation, head),
            "generated_at": generated_at,
        }
        if registration:
            element = build_registration_record(invoice=document, **chain)
        else:
            element = build_cancellation_record(cancellation=document, **chain)
        record = Record(
            installation=installation,
            position=head.position + 1 if head else 1,
            content_object=obj,
            operation=Operation.REGISTRATION if registration else Operation.CANCELLATION,
            amendment=registration and document.amendment,
            invoice_number=document.invoice_number,
            issue_date=document.issue_date,
            generated_at=generated_at,
            fingerprint=element.findtext(tag(RECORDS, "Huella")),
            xml=etree.tostring(element, encoding="unicode"),
        )
        models.Model.save(record, force_insert=True, using=using)
        transaction.on_commit(
            lambda: record_created.send_robust(Record, record=record), using=using, robust=True
        )
    return record


# Orden HAC/1177/2024, art. 7.i and 7.j: a problem is announced, but invoicing never stops.
def _check_head(installation: Installation, head: Record, generated_at, using: str) -> None:
    records = installation.records.using(using)
    previous = records.filter(position=head.position - 1).defer("xml").first()
    problems = record_problems(installation, head, previous, head.position)
    if head.generated_at > generated_at + timedelta(minutes=1):
        where = f"{installation} #{head.position} ({head})"
        problems.append(f"{where}: it was generated more than a minute after now")
    if not problems:
        return
    for problem in problems:
        logger.error("VERI*FACTU chain problem: %s", problem)

    def alarm():
        alarm_raised.send_robust(Installation, installation=installation, problems=problems)

    transaction.on_commit(alarm, using=using, robust=True)


def _database(obj: models.Model) -> str:
    if obj.pk is None or obj._state.adding:
        raise ImproperlyConfigured("save the object before registering its invoice")
    if not any(isinstance(field, VerifactuRecords) for field in obj._meta.private_fields):
        name = type(obj).__name__
        raise ImproperlyConfigured(f"add verifactu_records = VerifactuRecords() to {name}")
    using = router.db_for_write(Record, instance=obj)
    if obj._state.db != using:
        raise ImproperlyConfigured("VERI*FACTU records must live in the database of the object")
    if not transaction.get_connection(using).in_atomic_block:
        raise TransactionManagementError("register the invoice inside the transaction saving it")
    return using


# Restarts the taxpayer's chain, for example after restoring a backup or changing the software:
# the next records open a new generation with a new NumeroInstalacion and PrimerRegistro.
def new_installation(taxpayer_tax_id: str) -> Installation:
    if not is_valid_nif(taxpayer_tax_id):
        raise ValueError(f"{taxpayer_tax_id} is not a valid NIF")
    using = router.db_for_write(Installation)
    lookup = {"production": conf.production(), "taxpayer_tax_id": taxpayer_tax_id}
    with transaction.atomic(using=using):
        # The first chain comes with the first record: a stray taxpayer would be counted forever.
        if not (locked := _locked(lookup, using)):
            raise ValueError(f"{taxpayer_tax_id} has no chain to restart in this environment")
        installation = Installation(
            **lookup,
            generation=locked[-1].generation + 1,
            number=uuid4().hex.upper(),
            system_id=conf.software("", False).system_id,
            created_at=timezone.now(),
        )
        models.Model.save(installation, force_insert=True, using=using)
    return installation


# A generation created while this waited for the lock is not among the rows it locked, so
# lock again until nothing new appears.
def _locked(lookup: dict, using: str) -> list[Installation]:
    installations = Installation.objects.using(using).select_for_update().filter(**lookup)
    locked = None
    while True:
        rows = list(installations.order_by("generation"))
        if not rows or rows == locked:
            return rows
        locked = rows


def _installation(taxpayer_tax_id: str, using: str) -> Installation:
    production = conf.production()
    system_id = conf.software("", False).system_id
    lookup = {"production": production, "taxpayer_tax_id": taxpayer_tax_id}
    # A concurrent first registration wins the insert; the retry then locks its row. Under
    # REPEATABLE READ that row stays invisible, so the second failure is raised.
    for attempt in range(2):
        if installations := _locked(lookup, using):
            installation = max(installations, key=attrgetter("generation"))
            if installation.system_id != system_id:
                raise ImproperlyConfigured("SOFTWARE system_id changed: start a new installation")
            return installation
        installation = Installation(
            **lookup,
            generation=1,
            number=uuid4().hex.upper(),
            system_id=system_id,
            created_at=timezone.now(),
        )
        try:
            with transaction.atomic(using=using):
                models.Model.save(installation, force_insert=True, using=using)
        except IntegrityError:
            if attempt:
                raise
            continue
        return installation


# The AEAT wants it counted by the system, whatever state the taxpayers are in.
def _multiple_taxpayers(installation: Installation, using: str) -> bool:
    tax_id = installation.taxpayer_tax_id
    multiple = conf.multiple_taxpayers(tax_id)
    if multiple is None:
        others = Installation.objects.using(using).filter(production=installation.production)
        multiple = bool(conf.configured_taxpayers() - {tax_id})
        multiple = multiple or others.exclude(taxpayer_tax_id=tax_id).exists()
    if multiple and not conf.software("", False).multiple_taxpayers_possible:
        raise ImproperlyConfigured("SOFTWARE declares a single taxpayer, but there are more")
    return multiple


def _history(installation: Installation, number: str, issue_date, using: str) -> list[Record]:
    records = Record.objects.using(using).filter(
        installation__production=installation.production,
        installation__taxpayer_tax_id=installation.taxpayer_tax_id,
        invoice_number=number,
        issue_date=issue_date,
    )
    records = records.defer("xml").order_by("installation__generation", "position")
    # Compared again in Python: MySQL collations ignore case, the AEAT does not.
    return [record for record in records if record.invoice_number == number]


def _check_owner(
    obj: models.Model,
    installation: Installation,
    document: Invoice | Cancellation,
    history: list[Record],
    using: str,
) -> None:
    # Rejected records are not at the AEAT, so they bind no invoice to an object.
    owner = (ContentType.objects.db_manager(using).get_for_model(obj).pk, str(obj.pk))
    live = [record for record in history if record.status != Record.Status.REJECTED]
    if any((record.content_type_id, record.object_id) != owner for record in live):
        raise LifecycleError(f"{document.invoice_number} belongs to another object")
    records = Record.objects.using(using).filter(
        installation__production=installation.production,
        content_type_id=owner[0],
        object_id=owner[1],
    )
    keys = records.exclude(status=Record.Status.REJECTED).values_list(
        "installation__taxpayer_tax_id", "invoice_number", "issue_date"
    )
    key = (installation.taxpayer_tax_id, document.invoice_number, document.issue_date)
    if any(other != key for other in keys):
        raise LifecycleError("the object already has records of another invoice")


def _previous(installation: Installation, head: Record | None) -> PreviousRecord | None:
    if head is None:
        return None
    return PreviousRecord(
        installation.taxpayer_tax_id, head.invoice_number, head.issue_date, head.fingerprint
    )
