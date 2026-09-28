import logging
import ssl
from datetime import timedelta
from functools import lru_cache
from itertools import takewhile
from operator import itemgetter

from django.db import IntegrityError, models, router, transaction
from django.db.models import F, Min
from django.utils import timezone
from lxml import etree

from django_verifactu import conf
from django_verifactu.aeat.codes import DuplicateStatus, Operation, RecordStatus
from django_verifactu.aeat.domain import RecordResult, SubmissionResult
from django_verifactu.aeat.soap import (
    AeatFault,
    NotDelivered,
    OutcomeUnknown,
    Refused,
    parse_response,
)
from django_verifactu.aeat.submission import MAX_RECORDS, build_submission, submission_allowed
from django_verifactu.aeat.transport import client_ssl_context, post
from django_verifactu.models import Installation, Record, Submission, SubmissionLine
from django_verifactu.signals import record_answered, submission_finished

logger = logging.getLogger("django_verifactu")
_MAX_PAUSE = 900
# Requests have no overall time limit (httpx limits each read and write), so the window is
# generous: after it, the sender that claimed the submission is considered gone.
_STALE = timedelta(minutes=10)
_ADOPTED = {
    DuplicateStatus.VALID: Record.Status.ACCEPTED,
    DuplicateStatus.CANCELLED: Record.Status.ACCEPTED,
    DuplicateStatus.ACCEPTED_WITH_ERRORS: Record.Status.ACCEPTED_WITH_ERRORS,
}
_STATUSES = {
    RecordStatus.ACCEPTED: Record.Status.ACCEPTED,
    RecordStatus.ACCEPTED_WITH_ERRORS: Record.Status.ACCEPTED_WITH_ERRORS,
    RecordStatus.REJECTED: Record.Status.REJECTED,
}


class _NotDue(Exception):
    pass


def send_pending(*, taxpayer_tax_id: str | None = None) -> list[Submission]:
    using = router.db_for_write(Submission)
    _recover_stale(using)
    pending = Record.objects.using(using).filter(
        status=Record.Status.PENDING, installation__production=conf.production()
    )
    if taxpayer_tax_id is not None:
        pending = pending.filter(installation__taxpayer_tax_id=taxpayer_tax_id)
    fields = pending.values("installation", "installation__taxpayer_tax_id")
    oldest = fields.annotate(oldest=Min("generated_at")).order_by("installation__generation")
    # A newer generation may amend or cancel an older one's invoices, so only the oldest
    # generation with pending records of each taxpayer is sent.
    first = {}
    for row in oldest:
        first.setdefault(row["installation__taxpayer_tax_id"], row)
    order = [row["installation"] for row in sorted(first.values(), key=itemgetter("oldest"))]
    installations = Installation.objects.using(using).in_bulk(order)
    submissions = []
    for installation in map(installations.get, order):
        if submission := _send(installation, using):
            submissions.append(submission)
            # The AEAT or the network is down for every taxpayer.
            if submission.outcome == Submission.Outcome.NOT_DELIVERED:
                break
    return submissions


# The request of a stale submission went out when it was created, so the flow control
# counts from then.
def _recover_stale(using: str) -> None:
    stale = Submission._writes.using(using).filter(
        in_flight__isnull=False, created_at__lt=timezone.now() - _STALE
    )
    stale.update(in_flight=None, outcome=Submission.Outcome.UNKNOWN, finished_at=F("created_at"))


def _send(installation: Installation, using: str) -> Submission | None:
    claimed = _claim(installation, using)
    if claimed is None:
        return None
    submission, records = claimed
    # Unusable credentials fail this attempt too, so the resend declares the incident.
    try:
        taxpayer = conf.taxpayer(installation.taxpayer_tax_id)
        ssl_context = _ssl_context(taxpayer.certificate, taxpayer.password)
        content = post(
            build_submission(
                taxpayer_tax_id=installation.taxpayer_tax_id,
                taxpayer_name=taxpayer.name,
                records=[etree.fromstring(record.xml) for record in records],
                representative=taxpayer.representative,
                verifactu_end_date=taxpayer.verifactu_end_date,
                incident=submission.incident,
            ),
            ssl_context=ssl_context,
            production=installation.production,
            seal_certificate=taxpayer.seal,
        )
    except NotDelivered as failure:
        return _finish(submission, using, Submission.Outcome.NOT_DELIVERED, response=str(failure))
    except OutcomeUnknown as failure:
        return _finish(submission, using, Submission.Outcome.UNKNOWN, response=str(failure))
    except Refused as failure:
        return _finish(submission, using, Submission.Outcome.FAULT, response=str(failure))
    except Exception as failure:
        logger.exception("submission %s could not be built or sent", submission.pk)
        # Never repr(): it repeats arguments, such as a password that could not be encoded.
        response = f"{type(failure).__name__}: {failure}"
        return _finish(submission, using, Submission.Outcome.FAULT, response=response)
    answer = content.decode(errors="replace")
    try:
        result = parse_response(content)
    except AeatFault as fault:
        outcome = Submission.Outcome.FAULT
        return _finish(submission, using, outcome, error_code=fault.error_code, response=answer)
    except Exception:
        return _finish(submission, using, Submission.Outcome.UNKNOWN, response=answer)
    return _answered(submission, records, result, answer, using)


def _claim(installation: Installation, using: str) -> tuple[Submission, list[Record]] | None:
    pending = installation.records.using(using).filter(status=Record.Status.PENDING)
    records = list(pending.order_by("position")[:MAX_RECORDS])
    # Checked before claiming, so most passes write nothing, and again once claimed.
    if not records or not _due(installation, len(records), using):
        return None
    records, incident = _same_incident(records, using)
    environment = "P" if installation.production else "T"
    submission = Submission(
        installation=installation,
        in_flight=f"{environment}:{installation.taxpayer_tax_id}",
        incident=incident,
        created_at=timezone.now(),
    )
    try:
        with transaction.atomic(using=using, durable=True):
            try:
                with transaction.atomic(using=using):
                    models.Model.save(submission, force_insert=True, using=using)
            except IntegrityError:
                return None
            if not _due(installation, len(records), using, current=submission):
                raise _NotDue
            SubmissionLine._writes.using(using).bulk_create(
                SubmissionLine(submission=submission, record=record) for record in records
            )
    except _NotDue:
        return None
    return submission, records


# A technical incident delayed the records that already had an attempt without an answer.
# Only they declare it, so the batch stops where that changes.
def _same_incident(records: list[Record], using: str) -> tuple[list[Record], bool]:
    unanswered = set(
        SubmissionLine.objects.using(using)
        .filter(record__in=records, status__isnull=True, submission__finished_at__isnull=False)
        .values_list("record_id", flat=True)
    )
    incident = records[0].pk in unanswered
    run = list(takewhile(lambda record: (record.pk in unanswered) == incident, records))
    return run, incident


# Orden HAC/1177/2024 art. 16.2: the AEAT's waiting time since the previous submission, or
# 1000 pending records. After failures, a pause growing to 15 minutes, never shorter than
# that waiting time and still within the hourly retry of art. 16.4.
def _due(installation: Installation, pending: int, using: str, current=None) -> bool:
    earlier = (
        Submission.objects.using(using)
        .filter(
            installation__production=installation.production,
            installation__taxpayer_tax_id=installation.taxpayer_tax_id,
            finished_at__isnull=False,
        )
        .exclude(pk=getattr(current, "pk", None))
        .only("outcome", "created_at", "finished_at", "wait_seconds")
        .order_by("-created_at")
    )
    answered = earlier.filter(outcome=Submission.Outcome.ANSWERED).first()
    failed = earlier.exclude(outcome=Submission.Outcome.ANSWERED)
    if answered is not None:
        failed = failed.filter(created_at__gt=answered.created_at)
    failures = list(failed[:5])
    now = timezone.now()
    if not failures:
        if answered is None:
            return True
        return submission_allowed(
            pending=pending,
            last_sent_at=answered.finished_at,
            wait_seconds=answered.wait_seconds,
            now=now,
        )
    pause = min(60 * 2 ** (len(failures) - 1), _MAX_PAUSE)
    if answered is not None:
        pause = max(pause, answered.wait_seconds)
    return now >= failures[0].finished_at + timedelta(seconds=pause)


def _finish(submission: Submission, using: str, outcome: str, **answer) -> Submission:
    with transaction.atomic(using=using, durable=True):
        _close(submission, using, outcome, **answer)
    submission_finished.send_robust(Submission, submission=submission)
    return submission


def _close(submission: Submission, using: str, outcome: str, **answer) -> bool:
    fields = {"in_flight": None, "outcome": outcome, "finished_at": timezone.now(), **answer}
    open_outcomes = [Submission.Outcome.SENDING]
    # An answer that arrives after the submission was recovered is still the AEAT's answer:
    # it is kept, and records only move from pending, so a later resend is harmless.
    if outcome == Submission.Outcome.ANSWERED:
        open_outcomes.append(Submission.Outcome.UNKNOWN)
    closed = Submission._writes.using(using).filter(
        pk=submission.pk, outcome__in=open_outcomes
    )
    if not closed.update(**fields):
        return False
    for name, value in fields.items():
        setattr(submission, name, value)
    return True


def _answered(
    submission: Submission,
    records: list[Record],
    result: SubmissionResult,
    answer: str,
    using: str,
) -> Submission:
    answered = []
    # A 3000 after an attempt whose answer was lost is the record itself, stored back then.
    uncertain = set(
        SubmissionLine.objects.using(using)
        .filter(record__in=records, submission__outcome=Submission.Outcome.UNKNOWN)
        .values_list("record_id", flat=True)
    )
    with transaction.atomic(using=using, durable=True):
        stored = _close(
            submission,
            using,
            Submission.Outcome.ANSWERED,
            csv=result.csv or "",
            wait_seconds=result.wait_seconds,
            response=answer,
        )
        if stored:
            lines = submission.lines.using(using).order_by("pk")
            for line, record, line_answer in zip(lines, records, result.records):
                if _matches(submission.installation, record, line_answer):
                    adopt = record.pk in uncertain
                    answered.append(_store(line, record, line_answer, using, adopt))
    for record, line in answered:
        record_answered.send_robust(Record, record=record, line=line)
    submission_finished.send_robust(Submission, submission=submission)
    return submission


def _matches(installation: Installation, record: Record, answer: RecordResult) -> bool:
    expected = (installation.taxpayer_tax_id, record.invoice_number, record.issue_date)
    return (answer.issuer_tax_id, answer.invoice_number, answer.issue_date) == expected and (
        answer.operation == record.operation
    )


def _store(line: SubmissionLine, record: Record, answer: RecordResult, using: str, adopt: bool):
    duplicate = answer.duplicate.status if answer.duplicate else None
    outcome = {
        "error_code": answer.error_code,
        "error_description": answer.error_description or "",
    }
    SubmissionLine._writes.using(using).filter(pk=line.pk).update(
        status=answer.status, duplicate_status=duplicate, **outcome
    )
    status = _STATUSES[answer.status]
    stored = outcome
    if adopt and answer.error_code == 3000 and answer.duplicate and _landed(record, answer):
        status = _ADOPTED[answer.duplicate.status]
        stored = {
            "error_code": answer.duplicate.error_code,
            "error_description": answer.duplicate.error_description or "",
        }
    Record._writes.using(using).filter(pk=record.pk, status=Record.Status.PENDING).update(
        status=status, **stored
    )
    line.status, line.duplicate_status = answer.status, duplicate
    record.status = status
    for name, value in outcome.items():
        setattr(line, name, value)
    for name, value in stored.items():
        setattr(record, name, value)
    return record, line


def _landed(record: Record, answer: RecordResult) -> bool:
    # An amendment answered 3000 is one sent as missing at the AEAT (S+X): the invoice found
    # may be someone else's. A cancellation that landed can only have left it cancelled.
    if record.operation == Operation.CANCELLATION:
        return answer.duplicate.status == DuplicateStatus.CANCELLED
    return not record.amendment


# Bounded: each context holds about 0.7 MB, and a SaaS may serve thousands of taxpayers.
@lru_cache(maxsize=64)
def _ssl_context(certificate: bytes, password: str) -> ssl.SSLContext:
    return client_ssl_context(certificate, password)
