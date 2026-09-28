from lxml import etree

from django_verifactu.aeat.domain import BillingSoftware, InvoiceId, Party, Query
from django_verifactu.aeat.elements import QUERY, RECORDS, add, add_party, tag
from django_verifactu.aeat.formatting import format_date
from django_verifactu.aeat.identifiers import is_valid_nif
from django_verifactu.aeat.schemas import schema_violations
from django_verifactu.aeat.violations import ValidationError, Violation


def build_query(query: Query) -> etree._Element:
    violations = validate_query(query)
    if violations:
        raise ValidationError(violations)

    root = etree.Element(
        tag(QUERY, "ConsultaFactuSistemaFacturacion"), nsmap={"con": QUERY, "sum": RECORDS}
    )
    header = add(root, QUERY, "Cabecera")
    add(header, RECORDS, "IDVersion", "1.0")
    taxpayer = add(header, RECORDS, "Destinatario" if query.as_recipient else "ObligadoEmision")
    add(taxpayer, RECORDS, "NombreRazon", query.taxpayer_name)
    add(taxpayer, RECORDS, "NIF", query.taxpayer_tax_id)
    if query.as_representative:
        add(header, RECORDS, "IndicadorRepresentante", "S")

    filters = add(root, QUERY, "FiltroConsulta")
    period = add(filters, QUERY, "PeriodoImputacion")
    add(period, RECORDS, "Ejercicio", f"{query.year:04d}")
    add(period, RECORDS, "Periodo", f"{query.month:02d}")
    if query.invoice_number is not None:
        add(filters, QUERY, "NumSerieFactura", query.invoice_number)
    if query.counterparty is not None:
        add_party(add(filters, QUERY, "Contraparte"), query.counterparty)
    _add_issue_dates(filters, query)
    if query.software is not None:
        _add_software(add(filters, QUERY, "SistemaInformatico"), query.software)
    if query.external_reference is not None:
        add(filters, QUERY, "RefExterna", query.external_reference)
    if query.after is not None:
        _add_invoice_id(add(filters, QUERY, "ClavePaginacion"), query.after)
    if query.show_issuer_name or query.show_software:
        extra = add(root, QUERY, "DatosAdicionalesRespuesta")
        if query.show_issuer_name:
            add(extra, QUERY, "MostrarNombreRazonEmisor", "S")
        if query.show_software:
            add(extra, QUERY, "MostrarSistemaInformatico", "S")

    violations = schema_violations(root, "ConsultaLR")
    if violations:
        raise ValidationError(violations)
    return root


def validate_query(query: Query) -> list[Violation]:
    violations = []
    if not is_valid_nif(query.taxpayer_tax_id):
        code = 1239 if query.as_recipient else 4116
        violations.append(Violation(code, "taxpayer_tax_id is not a valid NIF"))
    if not 1 <= query.month <= 12:
        violations.append(Violation(1248, "month must be between 1 and 12"))
    if query.as_recipient and query.as_representative:
        violations.append(Violation(1261, "as_representative is for issuer queries only"))
    if query.as_recipient and query.show_software:
        violations.append(Violation(1272, "show_software is for issuer queries only"))
    if query.invoice_number is not None and not 1 <= len(query.invoice_number) <= 60:
        violations.append(Violation(1104, "invoice_number must have 1 to 60 characters"))
    if query.counterparty is not None:
        violations += _check_party(query.counterparty, "counterparty")
    if query.software is not None:
        violations += _check_party(query.software.producer, "the software producer")
    start, end = query.issued_from, query.issued_to
    if query.issue_date is not None and (start is not None or end is not None):
        violations.append(Violation(4102, "issue_date and an issue range exclude each other"))
    # Verified live: the AEAT also refuses a range that starts and ends on the same day.
    if start is not None and end is not None and start >= end:
        violations.append(Violation(1250, "issued_from must be before issued_to"))
    return violations


def _check_party(party: Party, label: str) -> list[Violation]:
    if (party.tax_id is None) == (party.foreign_id is None):
        return [Violation(4102, f"{label} needs either tax_id or foreign_id")]
    if party.tax_id is not None and not is_valid_nif(party.tax_id):
        return [Violation(4109, f"{label} tax_id is not a valid NIF")]
    return []


def _add_issue_dates(filters: etree._Element, query: Query) -> None:
    if query.issue_date is None and query.issued_from is None and query.issued_to is None:
        return
    dates = add(filters, QUERY, "FechaExpedicionFactura")
    if query.issue_date is not None:
        add(dates, RECORDS, "FechaExpedicionFactura", format_date(query.issue_date))
        return
    span = add(dates, RECORDS, "RangoFechaExpedicion")
    if query.issued_from is not None:
        add(span, RECORDS, "Desde", format_date(query.issued_from))
    if query.issued_to is not None:
        add(span, RECORDS, "Hasta", format_date(query.issued_to))


def _add_software(element: etree._Element, software: BillingSoftware) -> None:
    add_party(element, software.producer)
    add(element, RECORDS, "IdSistemaInformatico", software.system_id)
    add(element, RECORDS, "NumeroInstalacion", software.installation_number)


def _add_invoice_id(element: etree._Element, invoice: InvoiceId) -> None:
    add(element, RECORDS, "IDEmisorFactura", invoice.issuer_tax_id)
    add(element, RECORDS, "NumSerieFactura", invoice.invoice_number)
    add(element, RECORDS, "FechaExpedicionFactura", format_date(invoice.issue_date))
