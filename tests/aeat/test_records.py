from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from django_verifactu.aeat.codes import (
    CorrectionType,
    ExemptionCause,
    IdType,
    InvoiceType,
    IssuedBy,
    OperationQualification,
    PreviousRejection,
    TaxType,
)
from django_verifactu.aeat.domain import (
    Cancellation,
    CorrectedAmounts,
    ForeignId,
    InvoiceId,
    Party,
    PreviousRecord,
    TaxLine,
)
from django_verifactu.aeat.fingerprint import cancellation_fingerprint, registration_fingerprint
from django_verifactu.aeat.records import (
    build_cancellation_record,
    build_registration_record,
    fingerprint_of,
)
from django_verifactu.aeat.schemas import get_schema
from django_verifactu.aeat.violations import ValidationError
from tests.aeat.sample import (
    GENERATED_AT,
    INVOICE,
    SOFTWARE,
    sample_cancellation,
    sample_registration,
)


def value(record, path: str) -> str:
    return record.findtext(path, namespaces={"sf": record.nsmap["sum1"]})


def test_first_record_is_valid_and_starts_the_chain():
    record = sample_registration()
    get_schema("SuministroInformacion").assertValid(record)
    assert value(record, "sf:Encadenamiento/sf:PrimerRegistro") == "S"


def test_totals_are_derived_from_the_lines():
    record = sample_registration()
    assert value(record, "sf:CuotaTotal") == "21.00"
    assert value(record, "sf:ImporteTotal") == "121.00"


def test_fingerprint_matches_the_values_written_in_the_xml():
    record = sample_registration()
    assert value(record, "sf:Huella") == registration_fingerprint(
        issuer_tax_id=value(record, "sf:IDFactura/sf:IDEmisorFactura"),
        invoice_number=value(record, "sf:IDFactura/sf:NumSerieFactura"),
        issue_date=value(record, "sf:IDFactura/sf:FechaExpedicionFactura"),
        invoice_type=value(record, "sf:TipoFactura"),
        total_tax=value(record, "sf:CuotaTotal"),
        total_amount=value(record, "sf:ImporteTotal"),
        previous_fingerprint="",
        generated_at=value(record, "sf:FechaHoraHusoGenRegistro"),
    )


def test_chained_record_references_the_previous_one():
    previous = PreviousRecord(
        issuer_tax_id="89890001K",
        invoice_number="A-2026/000",
        issue_date=date(2026, 9, 23),
        fingerprint="3C464DAF61ACB827C65FDA19F352A4E3BDC2C640E9E9FC4CC058073F38F12F60",
    )
    record = sample_registration(previous)
    get_schema("SuministroInformacion").assertValid(record)
    assert value(record, "sf:Encadenamiento/sf:RegistroAnterior/sf:Huella") == previous.fingerprint


def test_official_chained_cancellation_example():
    record = build_cancellation_record(
        cancellation=Cancellation("89890001K", "12345679/G34", date(2024, 1, 1)),
        software=SOFTWARE,
        previous=PreviousRecord(
            issuer_tax_id="89890001K",
            invoice_number="12345679/G34",
            issue_date=date(2024, 1, 1),
            fingerprint="F7B94CFD8924EDFF273501B01EE5153E4CE8F259766F88CF6ACB8935802A2B97",
        ),
        generated_at=datetime(2024, 1, 1, 19, 20, 40, tzinfo=ZoneInfo("Europe/Madrid")),
    )
    get_schema("SuministroInformacion").assertValid(record)
    assert value(record, "sf:Huella") == (
        "177547C0D57AC74748561D054A9CEC14B4C4EA23D1BEFD6F2E69E3A388F90C68"
    )


CHAINED = PreviousRecord("89890001K", "A-2026/000", date(2026, 9, 23), "3C46" * 16)


@pytest.mark.parametrize(
    "record",
    [
        sample_registration(),
        sample_registration(CHAINED),
        sample_cancellation(),
        sample_cancellation(CHAINED),
    ],
)
def test_the_fingerprint_can_be_recomputed_from_a_record(record):
    assert fingerprint_of(record) == value(record, "sf:Huella")


def test_a_recomputed_fingerprint_reveals_changes():
    record = sample_registration()
    record.find("sf:ImporteTotal", namespaces={"sf": record.nsmap["sum1"]}).text = "1.00"
    assert fingerprint_of(record) != value(record, "sf:Huella")


def test_cancellation_fingerprint_matches_the_values_written_in_the_xml():
    record = sample_cancellation()
    get_schema("SuministroInformacion").assertValid(record)
    assert value(record, "sf:Encadenamiento/sf:PrimerRegistro") == "S"
    assert value(record, "sf:Huella") == cancellation_fingerprint(
        issuer_tax_id=value(record, "sf:IDFactura/sf:IDEmisorFacturaAnulada"),
        invoice_number=value(record, "sf:IDFactura/sf:NumSerieFacturaAnulada"),
        issue_date=value(record, "sf:IDFactura/sf:FechaExpedicionFacturaAnulada"),
        previous_fingerprint="",
        generated_at=value(record, "sf:FechaHoraHusoGenRegistro"),
    )


def test_foreign_and_multiple_recipients():
    foreign = Party(name="Kunde GmbH", foreign_id=ForeignId(IdType.VAT_NUMBER, "DE123456789"))
    invoice = replace(INVOICE, recipients=(INVOICE.recipients[0], foreign))
    record = build_registration_record(
        invoice=invoice, software=SOFTWARE, previous=None, generated_at=GENERATED_AT
    )
    recipients = record.findall("sf:Destinatarios/sf:IDDestinatario", {"sf": record.nsmap["sum1"]})
    assert len(recipients) == 2
    assert value(recipients[1], "sf:IDOtro/sf:IDType") == "02"
    assert value(recipients[1], "sf:IDOtro/sf:ID") == "DE123456789"
    assert value(recipients[1], "sf:IDOtro/sf:CodigoPais") is None


def test_operation_date_is_written():
    invoice = replace(INVOICE, operation_date=date(2026, 9, 1))
    record = build_registration_record(
        invoice=invoice, software=SOFTWARE, previous=None, generated_at=GENERATED_AT
    )
    assert value(record, "sf:FechaOperacion") == "01-09-2026"


def test_records_are_checked_against_the_official_schema():
    with pytest.raises(ValidationError) as error:
        build_registration_record(
            invoice=replace(INVOICE, description="x" * 501),
            software=SOFTWARE,
            previous=None,
            generated_at=GENERATED_AT,
        )
    assert [violation.code for violation in error.value.violations] == [1100]


def build(invoice):
    return build_registration_record(
        invoice=invoice, software=SOFTWARE, previous=None, generated_at=GENERATED_AT
    )


N1 = OperationQualification.N1
ORIGINAL = InvoiceId("89890001K", "A-2026/000", date(2026, 9, 1))


def test_simplified_invoice_has_no_recipients():
    record = build(replace(INVOICE, invoice_type=InvoiceType.F2, recipients=()))
    assert value(record, "sf:TipoFactura") == "F2"
    assert record.find("sf:Destinatarios", {"sf": record.nsmap["sum1"]}) is None


def test_substitution_lists_the_corrected_invoice_and_amounts():
    invoice = replace(
        INVOICE,
        invoice_type=InvoiceType.R1,
        correction_type=CorrectionType.SUBSTITUTION,
        corrected_invoices=(ORIGINAL,),
        corrected_amounts=CorrectedAmounts(base=Decimal("100"), tax=Decimal("21")),
        coupon=True,
    )
    record = build(invoice)
    corrected = "sf:FacturasRectificadas/sf:IDFacturaRectificada"
    assert value(record, "sf:TipoRectificativa") == "S"
    assert value(record, f"{corrected}/sf:NumSerieFactura") == "A-2026/000"
    assert value(record, f"{corrected}/sf:FechaExpedicionFactura") == "01-09-2026"
    assert value(record, "sf:ImporteRectificacion/sf:BaseRectificada") == "100.00"
    assert value(record, "sf:ImporteRectificacion/sf:CuotaRectificada") == "21.00"
    assert value(record, "sf:Cupon") == "S"
    assert value(record, "sf:Huella") == registration_fingerprint(
        issuer_tax_id=invoice.issuer_tax_id,
        invoice_number=invoice.invoice_number,
        issue_date="24-09-2026",
        invoice_type="R1",
        total_tax="21.00",
        total_amount="121.00",
        previous_fingerprint="",
        generated_at=value(record, "sf:FechaHoraHusoGenRegistro"),
    )


def test_replacement_invoice_lists_the_replaced_ones():
    record = build(replace(INVOICE, invoice_type=InvoiceType.F3, replaced_invoices=(ORIGINAL,)))
    assert value(record, "sf:FacturasSustituidas/sf:IDFacturaSustituida/sf:IDEmisorFactura") == (
        "89890001K"
    )


def test_invoice_flags_and_external_reference():
    record = build(replace(INVOICE, simplified_art_72_73=True, external_reference="PEDIDO-7"))
    assert value(record, "sf:FacturaSimplificadaArt7273") == "S"
    assert value(record, "sf:RefExterna") == "PEDIDO-7"
    simplified = build(
        replace(INVOICE, invoice_type=InvoiceType.F2, recipients=(), without_recipient_art_61d=True)
    )
    assert value(simplified, "sf:FacturaSinIdentifDestinatarioArt61d") == "S"


def test_macrodato_is_derived_from_the_total():
    big = (TaxLine(rate=Decimal("21"), base=Decimal("100000000"), tax=Decimal("21000000")),)
    assert value(build(replace(INVOICE, lines=big)), "sf:Macrodato") == "S"
    assert value(build(INVOICE), "sf:Macrodato") is None


def test_breakdown_lines_and_totals_with_surcharge():
    surcharged = TaxLine(
        base=Decimal("100"),
        rate=Decimal("21"),
        tax=Decimal("21"),
        surcharge_rate=Decimal("5.2"),
        surcharge=Decimal("5.20"),
    )
    exempt = TaxLine(base=Decimal("50"), qualification=None, exemption=ExemptionCause.E1)
    other_tax = TaxLine(base=Decimal("10"), tax_type=TaxType.OTHER, regime=None, qualification=N1)
    record = build(replace(INVOICE, lines=(surcharged, exempt, other_tax)))
    details = record.findall("sf:Desglose/sf:DetalleDesglose", {"sf": record.nsmap["sum1"]})
    assert value(details[0], "sf:CuotaRecargoEquivalencia") == "5.20"
    assert value(details[1], "sf:OperacionExenta") == "E1"
    assert value(details[1], "sf:CuotaRepercutida") is None
    assert value(details[2], "sf:Impuesto") == "05"
    assert value(details[2], "sf:ClaveRegimen") is None
    assert value(record, "sf:CuotaTotal") == "26.20"
    assert value(record, "sf:ImporteTotal") == "186.20"


def test_third_party_and_agreements_are_written():
    invoice = replace(
        INVOICE,
        issued_by=IssuedBy.THIRD_PARTY,
        third_party=Party("Gestoria", tax_id="12345678Z"),
        billing_agreement="AC-2026-1",
        system_agreement="SIS-1",
    )
    record = build(invoice)
    assert value(record, "sf:EmitidaPorTerceroODestinatario") == "T"
    assert value(record, "sf:Tercero/sf:NIF") == "12345678Z"
    assert value(record, "sf:NumRegistroAcuerdoFacturacion") == "AC-2026-1"
    assert value(record, "sf:IdAcuerdoSistemaInformatico") == "SIS-1"


def test_amendment_flags_are_written_after_the_issuer_name():
    plain = build(INVOICE)
    assert value(plain, "sf:Subsanacion") is None
    assert value(plain, "sf:RechazoPrevio") is None
    amended = build(
        replace(INVOICE, amendment=True, previous_rejection=PreviousRejection.NOT_AT_AEAT)
    )
    assert value(amended, "sf:Subsanacion") == "S"
    assert value(amended, "sf:RechazoPrevio") == "X"


@pytest.mark.parametrize(
    "change",
    [{"issuer_name": ""}, {"recipients": (Party(" ", tax_id="89890002E"),)}],
)
def test_blank_values_are_refused(change):
    with pytest.raises(ValidationError) as error:
        build(replace(INVOICE, **change))
    assert [violation.code for violation in error.value.violations] == [1100]
