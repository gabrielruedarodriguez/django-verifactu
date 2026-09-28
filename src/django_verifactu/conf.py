from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils.module_loading import import_string

from django_verifactu.aeat.domain import BillingSoftware, Party


def production() -> bool:
    return settings.VERIFACTU["PRODUCTION"]


# Records are dated in one fixed zone, never in the zone active for the request.
def time_zone() -> ZoneInfo:
    return ZoneInfo(settings.VERIFACTU.get("TIME_ZONE", "Europe/Madrid"))


def software(installation_number: str, multiple_taxpayers: bool) -> BillingSoftware:
    return BillingSoftware(
        **settings.VERIFACTU["SOFTWARE"],
        installation_number=installation_number,
        multiple_taxpayers=multiple_taxpayers,
    )


@dataclass(frozen=True)
class Taxpayer:
    name: str
    certificate: bytes | str | Path = field(repr=False)
    password: str = field(repr=False)
    seal: bool = False
    representative: Party | None = None
    # The last day this taxpayer sends as VERI*FACTU, when it renounces it.
    verifactu_end_date: date | None = None


# TAXPAYERS maps NIFs to Taxpayer fields, or names a function (tax_id) -> Taxpayer | None.
def taxpayer(tax_id: str) -> Taxpayer:
    taxpayers = settings.VERIFACTU["TAXPAYERS"]
    if isinstance(taxpayers, str):
        found = import_string(taxpayers)(tax_id)
    else:
        found = taxpayers.get(tax_id)
    if found is None:
        raise LookupError(f"VERIFACTU['TAXPAYERS'] has no credentials for {tax_id}")
    if not isinstance(found, Taxpayer):
        found = Taxpayer(**found)
    if not isinstance(found.certificate, bytes):
        try:
            certificate = Path(found.certificate).read_bytes()
        except OSError as error:
            # Raised anew: the original repeats the "path", which may be the certificate itself.
            raise OSError(f"cannot read the certificate of {tax_id}: {error.strerror}") from None
        found = replace(found, certificate=certificate)
    return found


# Every taxpayer the system holds counts for IndicadorMultiplesOT, even before it issues.
def configured_taxpayers() -> set[str]:
    taxpayers = settings.VERIFACTU.get("TAXPAYERS", {})
    return set(taxpayers) if isinstance(taxpayers, Mapping) else set()


# In a SaaS the AEAT counts the billings of each user, not of the whole service (FAQ for
# developers, section 4): MULTIPLE_TAXPAYERS names a function (tax_id) -> bool that does.
def multiple_taxpayers(tax_id: str) -> bool | None:
    hook = settings.VERIFACTU.get("MULTIPLE_TAXPAYERS")
    return None if hook is None else bool(import_string(hook)(tax_id))
