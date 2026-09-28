from datetime import datetime
from decimal import Decimal

from lxml import etree

from django_verifactu.aeat.domain import (
    BillingSoftware,
    Cancellation,
    Invoice,
    InvoiceId,
    PreviousRecord,
)
from django_verifactu.aeat.elements import RECORDS, add, add_party, tag
from django_verifactu.aeat.fingerprint import cancellation_fingerprint, registration_fingerprint
from django_verifactu.aeat.formatting import format_amount, format_date, format_timestamp
from django_verifactu.aeat.schemas import schema_violations
from django_verifactu.aeat.validation import (
    validate_cancellation,
    validate_chain,
    validate_invoice,
    validate_software,
)
from django_verifactu.aeat.violations import ValidationError

_VERSION = "1.0"
_SHA256 = "01"
_MACRODATO = Decimal("100000000")


def build_registration_record(
    *,
    invoice: Invoice,
    software: BillingSoftware,
    previous: PreviousRecord | None,
    generated_at: datetime,
) -> etree._Element:
    violations = validate_invoice(invoice, generated_at.date()) + validate_chain(previous)
    violations += validate_software(software, invoice.operation_date or invoice.issue_date)
    if violations:
        raise ValidationError(violations)

    issue_date = format_date(invoice.issue_date)
    charged = [(line.tax or 0) + (line.surcharge or 0) for line in invoice.lines]
    total_tax = format_amount(sum(charged, Decimal(0)))
    amount = sum((line.base for line in invoice.lines), Decimal(0)) + sum(charged, Decimal(0))
    total_amount = format_amount(amount)
    timestamp = format_timestamp(generated_at)

    record = _root("RegistroAlta")
    _add(record, "IDVersion", _VERSION)
    invoice_id = _add(record, "IDFactura")
    _add(invoice_id, "IDEmisorFactura", invoice.issuer_tax_id)
    _add(invoice_id, "NumSerieFactura", invoice.invoice_number)
    _add(invoice_id, "FechaExpedicionFactura", issue_date)
    _add_optional(record, "RefExterna", invoice.external_reference)
    _add(record, "NombreRazonEmisor", invoice.issuer_name)
    _add_flag(record, "Subsanacion", invoice.amendment)
    _add_optional(record, "RechazoPrevio", invoice.previous_rejection)
    _add(record, "TipoFactura", invoice.invoice_type)
    _add_optional(record, "TipoRectificativa", invoice.correction_type)
    corrected, replaced = invoice.corrected_invoices, invoice.replaced_invoices
    _add_references(record, "FacturasRectificadas", "IDFacturaRectificada", corrected)
    _add_references(record, "FacturasSustituidas", "IDFacturaSustituida", replaced)
    if invoice.corrected_amounts is not None:
        amounts = _add(record, "ImporteRectificacion")
        _add(amounts, "BaseRectificada", format_amount(invoice.corrected_amounts.base))
        _add(amounts, "CuotaRectificada", format_amount(invoice.corrected_amounts.tax))
    if invoice.operation_date is not None:
        _add(record, "FechaOperacion", format_date(invoice.operation_date))
    _add(record, "DescripcionOperacion", invoice.description)
    _add_flag(record, "FacturaSimplificadaArt7273", invoice.simplified_art_72_73)
    _add_flag(record, "FacturaSinIdentifDestinatarioArt61d", invoice.without_recipient_art_61d)
    _add_flag(record, "Macrodato", abs(amount) >= _MACRODATO)
    _add_optional(record, "EmitidaPorTerceroODestinatario", invoice.issued_by)
    if invoice.third_party is not None:
        add_party(_add(record, "Tercero"), invoice.third_party)
    if invoice.recipients:
        recipients = _add(record, "Destinatarios")
        for recipient in invoice.recipients:
            add_party(_add(recipients, "IDDestinatario"), recipient)
    _add_flag(record, "Cupon", invoice.coupon)

    breakdown = _add(record, "Desglose")
    for line in invoice.lines:
        detail = _add(breakdown, "DetalleDesglose")
        _add(detail, "Impuesto", line.tax_type)
        _add_optional(detail, "ClaveRegimen", line.regime)
        _add_optional(detail, "CalificacionOperacion", line.qualification)
        _add_optional(detail, "OperacionExenta", line.exemption)
        _add_amount(detail, "TipoImpositivo", line.rate)
        _add(detail, "BaseImponibleOimporteNoSujeto", format_amount(line.base))
        _add_amount(detail, "BaseImponibleACoste", line.base_at_cost)
        _add_amount(detail, "CuotaRepercutida", line.tax)
        _add_amount(detail, "TipoRecargoEquivalencia", line.surcharge_rate)
        _add_amount(detail, "CuotaRecargoEquivalencia", line.surcharge)

    _add(record, "CuotaTotal", total_tax)
    _add(record, "ImporteTotal", total_amount)
    _add_chain(record, previous)
    _add_software(record, software)
    _add(record, "FechaHoraHusoGenRegistro", timestamp)
    _add_optional(record, "NumRegistroAcuerdoFacturacion", invoice.billing_agreement)
    _add_optional(record, "IdAcuerdoSistemaInformatico", invoice.system_agreement)
    _add(record, "TipoHuella", _SHA256)
    _add(
        record,
        "Huella",
        registration_fingerprint(
            issuer_tax_id=invoice.issuer_tax_id,
            invoice_number=invoice.invoice_number,
            issue_date=issue_date,
            invoice_type=invoice.invoice_type,
            total_tax=total_tax,
            total_amount=total_amount,
            previous_fingerprint=previous.fingerprint if previous else "",
            generated_at=timestamp,
        ),
    )
    return _checked(record)


def build_cancellation_record(
    *,
    cancellation: Cancellation,
    software: BillingSoftware,
    previous: PreviousRecord | None,
    generated_at: datetime,
) -> etree._Element:
    violations = validate_cancellation(cancellation) + validate_chain(previous)
    violations += validate_software(software, cancellation.issue_date)
    if violations:
        raise ValidationError(violations)

    issue_date = format_date(cancellation.issue_date)
    timestamp = format_timestamp(generated_at)

    record = _root("RegistroAnulacion")
    _add(record, "IDVersion", _VERSION)
    invoice_id = _add(record, "IDFactura")
    _add(invoice_id, "IDEmisorFacturaAnulada", cancellation.issuer_tax_id)
    _add(invoice_id, "NumSerieFacturaAnulada", cancellation.invoice_number)
    _add(invoice_id, "FechaExpedicionFacturaAnulada", issue_date)
    _add_optional(record, "RefExterna", cancellation.external_reference)
    _add_flag(record, "SinRegistroPrevio", cancellation.without_previous_record)
    _add_flag(record, "RechazoPrevio", cancellation.previous_rejection)
    _add_optional(record, "GeneradoPor", cancellation.generated_by)
    if cancellation.generator is not None:
        add_party(_add(record, "Generador"), cancellation.generator)
    _add_chain(record, previous)
    _add_software(record, software)
    _add(record, "FechaHoraHusoGenRegistro", timestamp)
    _add(record, "TipoHuella", _SHA256)
    _add(
        record,
        "Huella",
        cancellation_fingerprint(
            issuer_tax_id=cancellation.issuer_tax_id,
            invoice_number=cancellation.invoice_number,
            issue_date=issue_date,
            previous_fingerprint=previous.fingerprint if previous else "",
            generated_at=timestamp,
        ),
    )
    return _checked(record)


# Recomputed from the values written in the record, to verify a stored one.
def fingerprint_of(record: etree._Element) -> str:
    def text(path: str) -> str:
        return record.findtext("/".join(tag(RECORDS, name) for name in path.split("/"))) or ""

    previous = text("Encadenamiento/RegistroAnterior/Huella")
    generated_at = text("FechaHoraHusoGenRegistro")
    if record.tag == tag(RECORDS, "RegistroAnulacion"):
        return cancellation_fingerprint(
            issuer_tax_id=text("IDFactura/IDEmisorFacturaAnulada"),
            invoice_number=text("IDFactura/NumSerieFacturaAnulada"),
            issue_date=text("IDFactura/FechaExpedicionFacturaAnulada"),
            previous_fingerprint=previous,
            generated_at=generated_at,
        )
    return registration_fingerprint(
        issuer_tax_id=text("IDFactura/IDEmisorFactura"),
        invoice_number=text("IDFactura/NumSerieFactura"),
        issue_date=text("IDFactura/FechaExpedicionFactura"),
        invoice_type=text("TipoFactura"),
        total_tax=text("CuotaTotal"),
        total_amount=text("ImporteTotal"),
        previous_fingerprint=previous,
        generated_at=generated_at,
    )


def _add_chain(record: etree._Element, previous: PreviousRecord | None) -> None:
    chain = _add(record, "Encadenamiento")
    if previous is None:
        _add(chain, "PrimerRegistro", "S")
        return
    link = _add(chain, "RegistroAnterior")
    _add(link, "IDEmisorFactura", previous.issuer_tax_id)
    _add(link, "NumSerieFactura", previous.invoice_number)
    _add(link, "FechaExpedicionFactura", format_date(previous.issue_date))
    _add(link, "Huella", previous.fingerprint)


def _add_references(
    record: etree._Element, name: str, item: str, invoices: tuple[InvoiceId, ...]
) -> None:
    if not invoices:
        return
    block = _add(record, name)
    for reference in invoices:
        element = _add(block, item)
        _add(element, "IDEmisorFactura", reference.issuer_tax_id)
        _add(element, "NumSerieFactura", reference.invoice_number)
        _add(element, "FechaExpedicionFactura", format_date(reference.issue_date))


def _add_optional(parent: etree._Element, name: str, text: str | None) -> None:
    if text is not None:
        _add(parent, name, text)


def _add_amount(parent: etree._Element, name: str, value: Decimal | None) -> None:
    if value is not None:
        _add(parent, name, format_amount(value))


def _add_flag(parent: etree._Element, name: str, flag: bool) -> None:
    if flag:
        _add(parent, name, "S")


def _checked(record: etree._Element) -> etree._Element:
    violations = schema_violations(record, "SuministroInformacion")
    if violations:
        raise ValidationError(violations)
    return record


def _add_software(record: etree._Element, software: BillingSoftware) -> None:
    system = _add(record, "SistemaInformatico")
    add_party(system, software.producer)
    _add(system, "NombreSistemaInformatico", software.name)
    _add(system, "IdSistemaInformatico", software.system_id)
    _add(system, "Version", software.version)
    _add(system, "NumeroInstalacion", software.installation_number)
    _add(system, "TipoUsoPosibleSoloVerifactu", "S")
    _add(system, "TipoUsoPosibleMultiOT", _yes_no(software.multiple_taxpayers_possible))
    _add(system, "IndicadorMultiplesOT", _yes_no(software.multiple_taxpayers))


def _root(name: str) -> etree._Element:
    return etree.Element(tag(RECORDS, name), nsmap={"sum1": RECORDS})


def _add(parent: etree._Element, name: str, text: str | None = None) -> etree._Element:
    return add(parent, RECORDS, name, text)


def _yes_no(flag: bool) -> str:
    return "S" if flag else "N"
