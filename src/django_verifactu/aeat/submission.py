import copy
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from lxml import etree

from django_verifactu.aeat.domain import Party
from django_verifactu.aeat.elements import RECORDS, SUBMISSION, add, tag
from django_verifactu.aeat.formatting import format_date
from django_verifactu.aeat.identifiers import is_valid_nif
from django_verifactu.aeat.violations import ValidationError, Violation

MAX_RECORDS = 1000
MAX_NAME = 120
# Validaciones 3.1.1: VERI*FACTU must end on 31 December only from 2027 on.
_YEAR_END_ONLY_FROM = date(2027, 1, 1)


def build_submission(
    *,
    taxpayer_tax_id: str,
    taxpayer_name: str,
    records: Sequence[etree._Element],
    representative: Party | None = None,
    verifactu_end_date: date | None = None,
    incident: bool = False,
) -> etree._Element:
    violations = validate_submission(
        taxpayer_tax_id=taxpayer_tax_id,
        taxpayer_name=taxpayer_name,
        records=records,
        representative=representative,
        verifactu_end_date=verifactu_end_date,
        today=_aeat_today(),
    )
    if violations:
        raise ValidationError(violations)

    submission = etree.Element(
        tag(SUBMISSION, "RegFactuSistemaFacturacion"),
        nsmap={"sum": SUBMISSION, "sum1": RECORDS},
    )
    header = add(submission, SUBMISSION, "Cabecera")
    taxpayer = add(header, RECORDS, "ObligadoEmision")
    add(taxpayer, RECORDS, "NombreRazon", taxpayer_name)
    add(taxpayer, RECORDS, "NIF", taxpayer_tax_id)
    if representative is not None:
        agent = add(header, RECORDS, "Representante")
        add(agent, RECORDS, "NombreRazon", representative.name)
        add(agent, RECORDS, "NIF", representative.tax_id)
    if verifactu_end_date is not None or incident:
        voluntary = add(header, RECORDS, "RemisionVoluntaria")
        if verifactu_end_date is not None:
            add(voluntary, RECORDS, "FechaFinVeriFactu", format_date(verifactu_end_date))
        if incident:
            add(voluntary, RECORDS, "Incidencia", "S")

    for record in records:
        add(submission, SUBMISSION, "RegistroFactura").append(copy.deepcopy(record))
    return submission


# Orden HAC/1177/2024, art. 16.2: wait the seconds of the last answer since the previous
# submission, or until a full submission of records is pending.
def submission_allowed(
    *, pending: int, last_sent_at: datetime | None, wait_seconds: int, now: datetime
) -> bool:
    if pending == 0:
        return False
    if last_sent_at is None or pending >= MAX_RECORDS:
        return True
    return now >= last_sent_at + timedelta(seconds=wait_seconds)


def validate_submission(
    *,
    taxpayer_tax_id: str,
    taxpayer_name: str,
    records: Sequence[etree._Element],
    representative: Party | None = None,
    verifactu_end_date: date | None = None,
    today: date,
) -> list[Violation]:
    if not records:
        return [Violation(4102, "a submission needs at least one record")]
    if len(records) > MAX_RECORDS:
        return [Violation(4114, f"a submission holds at most {MAX_RECORDS} records")]
    violations = validate_header(
        taxpayer_tax_id=taxpayer_tax_id,
        taxpayer_name=taxpayer_name,
        representative=representative,
        verifactu_end_date=verifactu_end_date,
        today=today,
    )
    return violations + [
        Violation(1108, f"record {index} was issued by someone other than the taxpayer")
        for index, record in enumerate(records)
        if _issuer(record) != taxpayer_tax_id
    ]


def validate_header(
    *,
    taxpayer_tax_id: str,
    taxpayer_name: str,
    representative: Party | None = None,
    verifactu_end_date: date | None = None,
    today: date,
) -> list[Violation]:
    violations = []
    if not is_valid_nif(taxpayer_tax_id):
        violations.append(Violation(4116, "taxpayer_tax_id is not a valid NIF"))
    violations += _check_name(taxpayer_name, "taxpayer_name")
    if representative is not None:
        if not is_valid_nif(representative.tax_id or ""):
            violations.append(Violation(4123, "the representative needs a valid NIF"))
        violations += _check_name(representative.name, "the representative name")
    if verifactu_end_date is not None:
        violations += _check_end_date(verifactu_end_date, today)
    return violations


def _check_name(name: str, label: str) -> list[Violation]:
    if not name.strip() or len(name) > MAX_NAME:
        return [Violation(1100, f"{label} must have 1 to {MAX_NAME} characters")]
    return []


def _check_end_date(end_date: date, today: date) -> list[Violation]:
    if end_date.year not in (today.year - 1, today.year):
        return [Violation(4120, "verifactu_end_date must be in this year or the last one")]
    if today >= _YEAR_END_ONLY_FROM and (end_date.month, end_date.day) != (12, 31):
        return [Violation(4120, "verifactu_end_date must be 31 December")]
    return []


# The AEAT decides the year by its clock in Madrid, which is UTC+1 when the year changes.
def _aeat_today() -> date:
    return (datetime.now(UTC) + timedelta(hours=1)).date()


def _issuer(record: etree._Element) -> str | None:
    invoice_id = record.find(tag(RECORDS, "IDFactura"))
    return invoice_id.findtext(tag(RECORDS, "IDEmisorFactura")) or invoice_id.findtext(
        tag(RECORDS, "IDEmisorFacturaAnulada")
    )
