from django import template
from django.utils.safestring import mark_safe

from django_verifactu.aeat.qr import LABEL, LEGEND, qr_svg
from django_verifactu.notices import notices
from django_verifactu.qr import qr_url

register = template.Library()


@register.inclusion_tag("django_verifactu/qr.html")
def verifactu_qr(obj) -> dict:
    url = qr_url(obj)
    return {"url": url, "svg": mark_safe(qr_svg(url)), "label": LABEL, "legend": LEGEND}


_EVERY_TAXPAYER = object()


# Without an argument, every taxpayer's notices; with an empty one (a NIF not filled in yet),
# none, so no one is shown another taxpayer's.
@register.inclusion_tag("django_verifactu/notices.html")
def verifactu_notices(taxpayer_tax_id=_EVERY_TAXPAYER) -> dict:
    if taxpayer_tax_id is _EVERY_TAXPAYER:
        return {"notices": notices()}
    return {"notices": notices(taxpayer_tax_id=taxpayer_tax_id) if taxpayer_tax_id else []}
