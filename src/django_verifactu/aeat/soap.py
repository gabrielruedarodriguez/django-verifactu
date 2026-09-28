import copy
import re
from datetime import date, datetime
from decimal import Decimal

from lxml import etree

from django_verifactu.aeat.codes import (
    DuplicateStatus,
    IdType,
    InvoiceType,
    Operation,
    RecordStatus,
    StoredStatus,
    SubmissionStatus,
)
from django_verifactu.aeat.domain import (
    BillingSoftware,
    DuplicateRecord,
    ForeignId,
    InvoiceId,
    Party,
    QueryPage,
    RecordResult,
    StoredRecord,
    SubmissionResult,
)
from django_verifactu.aeat.elements import QUERY_RESPONSE, RECORDS, RESPONSE, SOAP, add, tag


class AeatFault(Exception):
    def __init__(self, fault_code: str, message: str) -> None:
        super().__init__(message)
        self.fault_code = fault_code
        self.message = message
        code = re.match(r"Codigo\[(\d+)\]", message)
        self.error_code = int(code.group(1)) if code else None

    @property
    def retryable(self) -> bool:
        return self.fault_code.rpartition(":")[2] == "Server"


# The request never reached the AEAT, or it refused it unprocessed: sending it again is safe.
class NotDelivered(Exception):
    pass


# The AEAT refused the request unprocessed because of the taxpayer's credentials: verified
# live, an unknown or expired certificate is redirected to an error page (erro4011).
class Refused(Exception):
    pass


# The AEAT may have processed the request. Sending the same records again is safe: altas
# it already holds answer 3000, and cancellations or amendments are applied again as they are.
class OutcomeUnknown(Exception):
    pass


class UnexpectedResponse(OutcomeUnknown):
    pass


def wrap_in_envelope(submission: etree._Element) -> bytes:
    envelope = etree.Element(tag(SOAP, "Envelope"), nsmap={"soapenv": SOAP})
    add(envelope, SOAP, "Header")
    add(envelope, SOAP, "Body").append(copy.deepcopy(submission))
    return etree.tostring(envelope, xml_declaration=True, encoding="UTF-8")


def parse_response(content: bytes) -> SubmissionResult:
    answer = _answer(content, tag(RESPONSE, "RespuestaRegFactuSistemaFacturacion"))
    presentation = answer.find(tag(RESPONSE, "DatosPresentacion"))
    presented_at = presenter = None
    if presentation is not None:
        presented_at = _datetime(presentation.findtext(tag(RECORDS, "TimestampPresentacion")))
        presenter = presentation.findtext(tag(RECORDS, "NIFPresentador"))
    lines = answer.iterfind(tag(RESPONSE, "RespuestaLinea"))
    return SubmissionResult(
        status=SubmissionStatus(answer.findtext(tag(RESPONSE, "EstadoEnvio"))),
        csv=answer.findtext(tag(RESPONSE, "CSV")),
        wait_seconds=int(answer.findtext(tag(RESPONSE, "TiempoEsperaEnvio"))),
        presented_at=presented_at,
        presenter_tax_id=presenter,
        records=tuple(_record_result(line) for line in lines),
    )


def parse_query_response(content: bytes) -> QueryPage:
    answer = _answer(content, tag(QUERY_RESPONSE, "RespuestaConsultaFactuSistemaFacturacion"))
    record = tag(QUERY_RESPONSE, "RegistroRespuestaConsultaFactuSistemaFacturacion")
    key = answer.find(tag(QUERY_RESPONSE, "ClavePaginacion"))
    more = answer.findtext(tag(QUERY_RESPONSE, "IndicadorPaginacion")) == "S"
    return QueryPage(
        records=tuple(_stored_record(stored) for stored in answer.iterfind(record)),
        next_page=_invoice_id(key) if more and key is not None else None,
    )


def _answer(content: bytes, name: str) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        root = etree.fromstring(content, parser)
    except etree.XMLSyntaxError as error:
        raise UnexpectedResponse("the AEAT answer is not XML") from error
    body = root.find(tag(SOAP, "Body"))
    if body is None:
        raise UnexpectedResponse("the AEAT answer has no SOAP body")
    fault = body.find(tag(SOAP, "Fault"))
    if fault is not None:
        raise AeatFault(fault.findtext("faultcode") or "", fault.findtext("faultstring") or "")
    answer = body.find(name)
    if answer is None:
        raise UnexpectedResponse(f"the AEAT answer is not a {etree.QName(name).localname}")
    return answer


def _stored_record(record: etree._Element) -> StoredRecord:
    data = record.find(tag(QUERY_RESPONSE, "DatosRegistroFacturacion"))
    state = record.find(tag(QUERY_RESPONSE, "EstadoRegistro"))
    presentation = record.find(tag(QUERY_RESPONSE, "DatosPresentacion"))

    def stored(name: str) -> str | None:
        return data.findtext(tag(QUERY_RESPONSE, name))

    def presented(name: str) -> str | None:
        return None if presentation is None else presentation.findtext(tag(RECORDS, name))

    invoice_type = stored("TipoFactura")
    return StoredRecord(
        invoice=_invoice_id(record.find(tag(QUERY_RESPONSE, "IDFactura"))),
        status=StoredStatus(state.findtext(tag(QUERY_RESPONSE, "EstadoRegistro"))),
        error_code=_number(state.findtext(tag(QUERY_RESPONSE, "CodigoErrorRegistro"))),
        error_description=state.findtext(tag(QUERY_RESPONSE, "DescripcionErrorRegistro")),
        modified_at=_datetime(state.findtext(tag(QUERY_RESPONSE, "TimestampUltimaModificacion"))),
        invoice_type=InvoiceType(invoice_type) if invoice_type else None,
        description=stored("DescripcionOperacion"),
        total_tax=_decimal(stored("CuotaTotal")),
        total_amount=_decimal(stored("ImporteTotal")),
        external_reference=stored("RefExterna"),
        issuer_name=stored("NombreRazonEmisor"),
        software=_software(data.find(tag(QUERY_RESPONSE, "SistemaInformatico"))),
        generated_at=_datetime(stored("FechaHoraHusoGenRegistro")),
        fingerprint=stored("Huella"),
        presented_at=_datetime(presented("TimestampPresentacion")),
        presenter_tax_id=presented("NIFPresentador"),
        request_id=presented("IdPeticion"),
    )


def _software(element: etree._Element | None) -> BillingSoftware | None:
    if element is None:
        return None

    def text(name: str) -> str | None:
        return element.findtext(tag(RECORDS, name))

    return BillingSoftware(
        producer=_party(element),
        name=text("NombreSistemaInformatico"),
        system_id=text("IdSistemaInformatico"),
        version=text("Version"),
        installation_number=text("NumeroInstalacion"),
        multiple_taxpayers_possible=text("TipoUsoPosibleMultiOT") == "S",
        multiple_taxpayers=text("IndicadorMultiplesOT") == "S",
    )


def _party(element: etree._Element) -> Party:
    name = element.findtext(tag(RECORDS, "NombreRazon"))
    foreign = element.find(tag(RECORDS, "IDOtro"))
    if foreign is None:
        return Party(name, tax_id=element.findtext(tag(RECORDS, "NIF")))
    foreign_id = ForeignId(
        IdType(foreign.findtext(tag(RECORDS, "IDType"))),
        foreign.findtext(tag(RECORDS, "ID")),
        foreign.findtext(tag(RECORDS, "CodigoPais")),
    )
    return Party(name, foreign_id=foreign_id)


def _invoice_id(element: etree._Element) -> InvoiceId:
    return InvoiceId(
        issuer_tax_id=element.findtext(tag(RECORDS, "IDEmisorFactura")),
        invoice_number=element.findtext(tag(RECORDS, "NumSerieFactura")),
        issue_date=_date(element.findtext(tag(RECORDS, "FechaExpedicionFactura"))),
    )


def _record_result(line: etree._Element) -> RecordResult:
    invoice_id = _invoice_id(line.find(tag(RESPONSE, "IDFactura")))
    operation = line.find(tag(RESPONSE, "Operacion"))
    return RecordResult(
        issuer_tax_id=invoice_id.issuer_tax_id,
        invoice_number=invoice_id.invoice_number,
        issue_date=invoice_id.issue_date,
        operation=Operation(operation.findtext(tag(RECORDS, "TipoOperacion"))),
        external_reference=line.findtext(tag(RESPONSE, "RefExterna")),
        status=RecordStatus(line.findtext(tag(RESPONSE, "EstadoRegistro"))),
        error_code=_number(line.findtext(tag(RESPONSE, "CodigoErrorRegistro"))),
        error_description=line.findtext(tag(RESPONSE, "DescripcionErrorRegistro")),
        duplicate=_duplicate(line.find(tag(RESPONSE, "RegistroDuplicado"))),
    )


def _duplicate(element: etree._Element | None) -> DuplicateRecord | None:
    if element is None:
        return None
    return DuplicateRecord(
        request_id=element.findtext(tag(RECORDS, "IdPeticionRegistroDuplicado")),
        status=DuplicateStatus(element.findtext(tag(RECORDS, "EstadoRegistroDuplicado"))),
        error_code=_number(element.findtext(tag(RECORDS, "CodigoErrorRegistro"))),
        error_description=element.findtext(tag(RECORDS, "DescripcionErrorRegistro")),
    )


def _number(text: str | None) -> int | None:
    return int(text) if text else None


def _decimal(text: str | None) -> Decimal | None:
    return Decimal(text) if text else None


def _date(text: str) -> date:
    return datetime.strptime(text, "%d-%m-%Y").date()


def _datetime(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None
