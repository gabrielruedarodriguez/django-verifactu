from datetime import timedelta
from typing import NamedTuple

from django.db import router
from django.db.models import Count, Min, OuterRef, Subquery
from django.utils import timezone

from django_verifactu import conf
from django_verifactu.models import Installation, Record, Submission
from django_verifactu.verifying import chain_problems

# The AEAT flags records more than 240 s away from its clock (2004).
_LATE = timedelta(seconds=240)
# The latest records of each chain checked for every notice.
_RECENT = 20


class Notice(NamedTuple):
    taxpayer_tax_id: str
    message: str


# What the user must be shown now (Orden HAC/1177/2024): records not sent because of an
# incident, with how many are left (art. 16.4), and problems in the latest records of a chain
# (art. 6.f and 7.j).
def notices(*, taxpayer_tax_id: str | None = None) -> list[Notice]:
    using = router.db_for_write(Record)
    installations = Installation.objects.using(using).filter(production=conf.production())
    if taxpayer_tax_id is not None:
        installations = installations.filter(taxpayer_tax_id=taxpayer_tax_id)
    heads = Record.objects.filter(installation=OuterRef("pk")).order_by("-position")
    installations = installations.annotate(head=Subquery(heads.values("position")[:1]))
    installations = list(installations.order_by("taxpayer_tax_id", "generation"))
    found = [
        Notice(tax_id, f"{count} VERI*FACTU records of {tax_id} could not be sent to the AEAT yet")
        for tax_id, count in _unsent(installations, using)
    ]
    for installation in installations:
        if installation.head is None:
            continue
        after = max(installation.head - _RECENT, -1)
        found += [
            Notice(installation.taxpayer_tax_id, f"The VERI*FACTU chain may be broken: {problem}")
            for problem in chain_problems(installation, using, after=after)
        ]
    return found


# Pending records are unsent because of an incident once a submission failed, or once they
# waited longer than the AEAT tolerates, whatever the cause.
def _unsent(installations: list[Installation], using: str) -> list[tuple[str, int]]:
    pending = Record.objects.using(using).filter(
        status=Record.Status.PENDING, installation__in=installations
    )
    by_taxpayer = pending.values("installation__taxpayer_tax_id").annotate(
        count=Count("pk"), oldest=Min("generated_at")
    )
    unsent = []
    for row in by_taxpayer.order_by("installation__taxpayer_tax_id"):
        tax_id = row["installation__taxpayer_tax_id"]
        own = [i for i in installations if i.taxpayer_tax_id == tax_id]
        finished = Submission.objects.using(using).filter(
            installation__in=own, finished_at__isnull=False
        )
        finished = finished.order_by("-created_at")
        last = finished.only("outcome").first()
        answered = finished.filter(outcome=Submission.Outcome.ANSWERED).only("wait_seconds").first()
        wait = timedelta(seconds=answered.wait_seconds or 0) if answered else timedelta()
        late = row["oldest"] < timezone.now() - max(_LATE, wait + timedelta(minutes=1))
        if late or (last is not None and last.outcome != Submission.Outcome.ANSWERED):
            unsent.append((tax_id, row["count"]))
    return unsent
