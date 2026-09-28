from django.contrib.contenttypes.models import ContentType
from django.db import models, router
from lxml import etree

from django_verifactu import conf
from django_verifactu.aeat import qr
from django_verifactu.aeat.codes import Operation
from django_verifactu.lifecycle import NotRegistered
from django_verifactu.models import Record


def qr_url(obj: models.Model) -> str:
    using = obj._state.db or router.db_for_read(Record, instance=obj)
    registrations = Record.objects.using(using).filter(
        content_type=ContentType.objects.db_manager(using).get_for_model(obj),
        object_id=str(obj.pk),
        installation__production=conf.production(),
        operation=Operation.REGISTRATION,
    )
    # The AEAT only matches the amount of the latest registration it accepted.
    live = registrations.exclude(status=Record.Status.REJECTED)
    record = live.order_by("installation__generation", "position").last()
    if record is None:
        raise NotRegistered(f"{obj} has no registration to print a QR code for")
    return qr.qr_url(etree.fromstring(record.xml), production=conf.production())
