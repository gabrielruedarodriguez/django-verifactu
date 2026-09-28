from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import DEFAULT_DB_ALIAS, models
from django.db.models import ProtectedError

from django_verifactu.aeat.codes import DuplicateStatus, Operation, RecordStatus
from django_verifactu.aeat.domain import NO_AMENDMENT_NEEDED


class ImmutableRecord(Exception):
    pass


def _refuse(self, *args, **kwargs):
    raise ImmutableRecord(f"{self.model.__name__} is written by django_verifactu only")


# VERI*FACTU evidence is written only by django_verifactu, inside its own transactions.
class _EvidenceQuerySet(models.QuerySet):
    create = get_or_create = update_or_create = bulk_create = bulk_update = _refuse
    update = delete = _refuse


class _Evidence(models.Model):
    objects = _EvidenceQuerySet.as_manager()
    # How django_verifactu itself records the AEAT answers.
    _writes = models.Manager()

    class Meta:
        abstract = True
        # Related managers (add, set) write through the base manager.
        base_manager_name = "objects"

    def save(self, *args, **kwargs):
        raise ImmutableRecord(f"{type(self).__name__} is written by django_verifactu only")

    def delete(self, *args, **kwargs):
        raise ImmutableRecord(f"{type(self).__name__} is written by django_verifactu only")


class Installation(_Evidence):
    production = models.BooleanField()
    taxpayer_tax_id = models.CharField(max_length=9)
    generation = models.PositiveSmallIntegerField()
    number = models.CharField(max_length=100, unique=True)
    system_id = models.CharField(max_length=2)
    created_at = models.DateTimeField()

    class Meta(_Evidence.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["production", "taxpayer_tax_id", "generation"],
                name="verifactu_unique_generation",
            )
        ]

    def __str__(self):
        environment = "production" if self.production else "test"
        return f"{self.taxpayer_tax_id} {environment} #{self.generation}"


class Record(_Evidence):
    class Status(models.TextChoices):
        PENDING = "pending"
        ACCEPTED = "accepted"
        ACCEPTED_WITH_ERRORS = "accepted_with_errors"
        REJECTED = "rejected"

    installation = models.ForeignKey(Installation, models.PROTECT, related_name="records")
    position = models.PositiveBigIntegerField()
    content_type = models.ForeignKey(ContentType, models.PROTECT)
    object_id = models.CharField(max_length=255)
    content_object = GenericForeignKey()
    operation = models.CharField(max_length=9, choices=[(op.value, op.value) for op in Operation])
    amendment = models.BooleanField(default=False)
    invoice_number = models.CharField(max_length=60)
    issue_date = models.DateField()
    generated_at = models.DateTimeField()
    fingerprint = models.CharField(max_length=64)
    xml = models.TextField()
    status = models.CharField(max_length=20, choices=Status, default=Status.PENDING)
    error_code = models.PositiveIntegerField(null=True)
    error_description = models.TextField(blank=True)

    class Meta(_Evidence.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["installation", "position"], name="verifactu_unique_position"
            )
        ]
        indexes = [
            models.Index(fields=["installation", "status", "position"]),
            models.Index(fields=["invoice_number", "issue_date"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.operation} {self.invoice_number} {self.issue_date:%d-%m-%Y}"

    @property
    def needs_amendment(self) -> bool:
        return (
            self.status == self.Status.ACCEPTED_WITH_ERRORS
            and self.error_code not in NO_AMENDMENT_NEEDED
        )


class Submission(_Evidence):
    class Outcome(models.TextChoices):
        SENDING = "sending"
        ANSWERED = "answered"
        FAULT = "fault"
        NOT_DELIVERED = "not_delivered"
        UNKNOWN = "unknown"

    # No database constraint: claiming a submission must never wait for an issuer's lock.
    installation = models.ForeignKey(
        Installation,
        models.PROTECT,
        related_name="submissions",
        db_constraint=False,
        db_index=False,
    )
    # Set while sending, so only one sender works for a taxpayer at a time.
    in_flight = models.CharField(max_length=11, null=True, unique=True)
    incident = models.BooleanField(default=False)
    created_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True)
    outcome = models.CharField(max_length=20, choices=Outcome, default=Outcome.SENDING)
    csv = models.CharField(max_length=100, blank=True)
    wait_seconds = models.PositiveIntegerField(null=True)
    error_code = models.PositiveIntegerField(null=True)
    response = models.TextField(blank=True)

    class Meta(_Evidence.Meta):
        indexes = [models.Index(fields=["installation", "created_at"])]

    def __str__(self):
        return f"Submission {self.pk} ({self.outcome})"


class SubmissionLine(_Evidence):
    submission = models.ForeignKey(
        Submission, models.PROTECT, related_name="lines", db_index=False
    )
    record = models.ForeignKey(Record, models.PROTECT, related_name="lines")
    status = models.CharField(
        max_length=20, null=True, choices=[(s.value, s.value) for s in RecordStatus]
    )
    error_code = models.PositiveIntegerField(null=True)
    error_description = models.TextField(blank=True)
    duplicate_status = models.CharField(
        max_length=20, null=True, choices=[(s.value, s.value) for s in DuplicateStatus]
    )

    class Meta(_Evidence.Meta):
        constraints = [
            models.UniqueConstraint(fields=["submission", "record"], name="verifactu_unique_line")
        ]


class VerifactuRecords(GenericRelation):
    def __init__(self, **kwargs):
        super().__init__(Record, **kwargs)

    # Refused while Django collects what to delete, before any row or transaction is touched.
    def bulk_related_objects(self, objs, using=DEFAULT_DB_ALIAS):
        records = super().bulk_related_objects(objs, using)
        if records.exists():
            raise ProtectedError("objects with VERI*FACTU records cannot be deleted", records)
        return records
