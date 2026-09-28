import ssl
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import httpx
import pytest
from lxml import etree

from django_verifactu.aeat.codes import IdType, InvoiceType, StoredStatus
from django_verifactu.aeat.domain import ForeignId, InvoiceId, Party
from django_verifactu.aeat.query import build_query, validate_query
from django_verifactu.aeat.schemas import get_schema
from django_verifactu.aeat.soap import AeatFault, parse_query_response
from django_verifactu.aeat.transport import send_query
from django_verifactu.aeat.violations import ValidationError
from tests.aeat.sample import (
    QUERY,
    SOAP,
    SOFTWARE,
    STORED_DATA,
    query_response,
    stored_error,
    stored_record,
)

KEY = InvoiceId("89890001K", "A-2026/000", date(2026, 9, 23))
CUSTOMER = Party("Cliente de prueba SL", tax_id="89890002E")
EVERYTHING = replace(
    QUERY,
    invoice_number="A-2026/001",
    counterparty=CUSTOMER,
    issued_from=date(2026, 9, 1),
    issued_to=date(2026, 9, 30),
    software=SOFTWARE,
    external_reference="ERP-1",
    after=KEY,
    show_issuer_name=True,
    show_software=True,
)


def value(element, path: str) -> str | None:
    return element.findtext(path, namespaces=element.nsmap)


def codes(**changes):
    return [violation.code for violation in validate_query(replace(QUERY, **changes))]


def test_minimal_query_asks_for_one_month_as_the_issuer():
    query = build_query(QUERY)
    get_schema("ConsultaLR").assertValid(query)
    assert value(query, "con:Cabecera/sum:ObligadoEmision/sum:NIF") == "89890001K"
    assert value(query, "con:FiltroConsulta/con:PeriodoImputacion/sum:Ejercicio") == "2026"
    assert value(query, "con:FiltroConsulta/con:PeriodoImputacion/sum:Periodo") == "09"
    assert value(query, "con:DatosAdicionalesRespuesta") is None


def test_every_filter_is_written_in_the_official_order():
    query = build_query(EVERYTHING)
    get_schema("ConsultaLR").assertValid(query)
    filters = "con:FiltroConsulta"
    assert value(query, f"{filters}/con:Contraparte/sum:NIF") == "89890002E"
    range_ = f"{filters}/con:FechaExpedicionFactura/sum:RangoFechaExpedicion"
    assert value(query, f"{range_}/sum:Desde") == "01-09-2026"
    assert value(query, f"{range_}/sum:Hasta") == "30-09-2026"
    assert value(query, f"{filters}/con:ClavePaginacion/sum:NumSerieFactura") == "A-2026/000"
    assert value(query, "con:DatosAdicionalesRespuesta/con:MostrarNombreRazonEmisor") == "S"
    assert value(query, "con:DatosAdicionalesRespuesta/con:MostrarSistemaInformatico") == "S"


def test_software_filter_uses_its_identity_only():
    query = build_query(EVERYTHING)
    system = query.find("con:FiltroConsulta/con:SistemaInformatico", query.nsmap)
    names = [etree.QName(element).localname for element in system]
    assert names == ["NombreRazon", "NIF", "IdSistemaInformatico", "NumeroInstalacion"]


def test_exact_issue_date_nests_two_elements_with_the_same_name():
    query = build_query(replace(QUERY, issue_date=date(2026, 9, 24)))
    get_schema("ConsultaLR").assertValid(query)
    path = "con:FiltroConsulta/con:FechaExpedicionFactura/sum:FechaExpedicionFactura"
    assert value(query, path) == "24-09-2026"


def test_recipient_query_and_representative_flag():
    recipient = build_query(replace(QUERY, as_recipient=True))
    assert value(recipient, "con:Cabecera/sum:Destinatario/sum:NIF") == "89890001K"
    representative = build_query(replace(QUERY, as_representative=True))
    assert value(representative, "con:Cabecera/sum:IndicadorRepresentante") == "S"


def test_sample_query_is_valid():
    assert codes() == []
    assert validate_query(EVERYTHING) == []


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"taxpayer_tax_id": "89890001A"}, [4116]),
        ({"taxpayer_tax_id": "89890001A", "as_recipient": True}, [1239]),
        ({"month": 0}, [1248]),
        ({"month": 13}, [1248]),
        ({"as_recipient": True, "as_representative": True}, [1261]),
        ({"as_recipient": True, "show_software": True}, [1272]),
        ({"invoice_number": ""}, [1104]),
        ({"invoice_number": "X" * 61}, [1104]),
        ({"counterparty": Party("Cliente")}, [4102]),
        ({"counterparty": Party("Cliente", tax_id="89890001A")}, [4109]),
        ({"software": replace(SOFTWARE, producer=Party("Productor"))}, [4102]),
        ({"software": replace(SOFTWARE, producer=Party("P", tax_id="89890001A"))}, [4109]),
        ({"issue_date": date(2026, 9, 24), "issued_from": date(2026, 9, 1)}, [4102]),
        ({"issued_from": date(2026, 9, 24), "issued_to": date(2026, 9, 24)}, [1250]),
        ({"issued_from": date(2026, 9, 25), "issued_to": date(2026, 9, 24)}, [1250]),
        ({"issued_from": date(2026, 9, 24)}, []),
    ],
)
def test_query_rules(changes, expected):
    assert codes(**changes) == expected


def test_foreign_counterparty_is_accepted():
    passport = Party("Kunde", foreign_id=ForeignId(IdType.PASSPORT, "AB123456", "FR"))
    query = build_query(replace(QUERY, counterparty=passport))
    get_schema("ConsultaLR").assertValid(query)


@pytest.mark.parametrize(
    "changes",
    [{"taxpayer_name": " "}, {"taxpayer_name": "x" * 121}, {"external_reference": "x" * 61}],
)
def test_values_outside_the_schema_cannot_become_a_query(changes):
    with pytest.raises(ValidationError) as error:
        build_query(replace(QUERY, **changes))
    assert [violation.code for violation in error.value.violations] == [1100]


def test_invalid_query_cannot_be_built():
    with pytest.raises(ValidationError):
        build_query(replace(QUERY, month=13))


PRESENTED_RECORD = stored_record()
SHOWN_SOFTWARE = """
      <r:SistemaInformatico>
        <tik:NombreRazon>Software House</tik:NombreRazon>
        <tik:IDOtro><tik:CodigoPais>US</tik:CodigoPais><tik:IDType>06</tik:IDType>
          <tik:ID>EIN-1</tik:ID></tik:IDOtro>
        <tik:NombreSistemaInformatico>Facturador</tik:NombreSistemaInformatico>
        <tik:IdSistemaInformatico>FA</tik:IdSistemaInformatico>
        <tik:Version>1.0</tik:Version>
        <tik:NumeroInstalacion>1</tik:NumeroInstalacion>
        <tik:TipoUsoPosibleSoloVerifactu>S</tik:TipoUsoPosibleSoloVerifactu>
        <tik:TipoUsoPosibleMultiOT>S</tik:TipoUsoPosibleMultiOT>
        <tik:IndicadorMultiplesOT>N</tik:IndicadorMultiplesOT>
      </r:SistemaInformatico>"""
SHOWN_RECORD = stored_record(
    data=STORED_DATA.replace(
        "<r:RefExterna>", "<r:NombreRazonEmisor>Emisor</r:NombreRazonEmisor><r:RefExterna>"
    ).replace("</r:Encadenamiento>", "</r:Encadenamiento>" + SHOWN_SOFTWARE)
)
WITH_ERRORS = stored_record(
    "AceptadoConErrores", stored_error(2001, "NIF no censado"), invoice_number="A-2026/002"
)
AS_RECIPIENT = stored_record(
    data="<r:TipoFactura>F1</r:TipoFactura><r:CuotaTotal>21</r:CuotaTotal>", presentation=""
)


@pytest.mark.parametrize(
    "sample",
    [
        query_response(),
        query_response(SHOWN_RECORD),
        query_response(PRESENTED_RECORD, WITH_ERRORS, next_page="A-2026/002"),
    ],
)
def test_sample_answers_follow_the_official_schema(sample):
    answer = etree.fromstring(sample).find(f"{{{SOAP}}}Body")[0]
    get_schema("RespuestaConsultaLR").assertValid(answer)


def test_answer_without_data():
    page = parse_query_response(query_response())
    assert page.records == ()
    assert page.next_page is None


def test_stored_record_is_read():
    [record] = parse_query_response(query_response(PRESENTED_RECORD)).records
    assert record.invoice == InvoiceId("89890001K", "A-2026/001", date(2026, 9, 24))
    assert record.status is StoredStatus.ACCEPTED
    assert record.modified_at == datetime.fromisoformat("2026-09-24T10:00:05+02:00")
    assert record.invoice_type is InvoiceType.F1
    assert record.description == "Servicios de consultoría"
    assert (record.total_tax, record.total_amount) == (Decimal(21), Decimal(121))
    assert record.external_reference == "ERP-1"
    assert record.generated_at == datetime.fromisoformat("2026-09-24T10:00:00+02:00")
    assert record.fingerprint.startswith("58CCBA95")
    assert record.presenter_tax_id == "12345678Z"
    assert record.request_id == "20260924100005"
    assert record.presented_at == datetime.fromisoformat("2026-09-24T10:00:05+02:00")
    assert record.error_code is None
    assert (record.issuer_name, record.software) == (None, None)
    assert not record.needs_amendment


def test_issuer_name_and_software_are_read_when_shown():
    [record] = parse_query_response(query_response(SHOWN_RECORD)).records
    assert record.issuer_name == "Emisor"
    software = record.software
    assert software.producer == Party(
        "Software House", foreign_id=ForeignId(IdType.OTHER_DOCUMENT, "EIN-1", "US")
    )
    assert (software.name, software.system_id, software.version) == ("Facturador", "FA", "1.0")
    assert software.installation_number == "1"
    assert (software.multiple_taxpayers_possible, software.multiple_taxpayers) == (True, False)


def test_recipients_see_the_invoice_but_not_the_record():
    [record] = parse_query_response(query_response(AS_RECIPIENT)).records
    assert record.total_tax == Decimal(21)
    assert (record.fingerprint, record.presented_at, record.request_id) == (None, None, None)


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        ("AceptadoConErrores", 2001, True),
        ("AceptadoConErrores", 2004, False),
        ("Anulado", None, False),
    ],
)
def test_stored_records_that_need_an_amendment(status, code, expected):
    error = stored_error(code, "NIF no censado") if code else ""
    [record] = parse_query_response(query_response(stored_record(status, error))).records
    assert record.needs_amendment is expected
    assert record.error_description == ("NIF no censado" if code else None)


def test_next_page_starts_after_the_answer_key():
    page = parse_query_response(query_response(PRESENTED_RECORD, next_page="A-2026/001"))
    assert page.next_page == InvoiceId("89890001K", "A-2026/001", date(2026, 9, 24))


def test_query_fault_is_raised():
    fault = f"""<env:Envelope xmlns:env="{SOAP}"><env:Body><env:Fault>
<faultcode>env:Client</faultcode><faultstring>Codigo[1248].Periodo incorrecto.</faultstring>
</env:Fault></env:Body></env:Envelope>""".encode()
    with pytest.raises(AeatFault) as raised:
        parse_query_response(fault)
    assert raised.value.error_code == 1248


def test_query_is_posted_to_the_verifactu_service():
    requests = []

    def aeat(request):
        requests.append(request)
        return httpx.Response(200, content=query_response(PRESENTED_RECORD))

    page = send_query(
        build_query(QUERY),
        ssl_context=ssl.create_default_context(),
        production=False,
        seal_certificate=False,
        transport=httpx.MockTransport(aeat),
    )
    [request] = requests
    assert request.url.path == "/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP"
    body = etree.fromstring(request.content).find(f"{{{SOAP}}}Body")
    assert etree.QName(body[0]).localname == "ConsultaFactuSistemaFacturacion"
    assert len(page.records) == 1
