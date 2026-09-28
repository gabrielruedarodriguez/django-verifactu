from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django_verifactu.aeat.domain import (
    BillingSoftware,
    Cancellation,
    Invoice,
    Party,
    PreviousRecord,
    Query,
    TaxLine,
)
from django_verifactu.aeat.records import build_cancellation_record, build_registration_record

INVOICE = Invoice(
    issuer_tax_id="89890001K",
    issuer_name="Emisor de prueba SL",
    invoice_number="A-2026/001",
    issue_date=date(2026, 9, 24),
    description="Servicios de consultoría",
    recipients=(Party(name="Cliente de prueba SL", tax_id="89890002E"),),
    lines=(TaxLine(rate=Decimal("21"), base=Decimal("100"), tax=Decimal("21")),),
)
SOFTWARE = BillingSoftware(
    producer=Party("Productor de prueba SL", tax_id="89890003T"),
    name="Facturador",
    system_id="FA",
    version="1.0",
    installation_number="1",
    multiple_taxpayers_possible=False,
    multiple_taxpayers=False,
)
CANCELLATION = Cancellation(
    issuer_tax_id=INVOICE.issuer_tax_id,
    invoice_number=INVOICE.invoice_number,
    issue_date=INVOICE.issue_date,
)
GENERATED_AT = datetime(2026, 9, 24, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
QUERY = Query(
    taxpayer_tax_id=INVOICE.issuer_tax_id, taxpayer_name=INVOICE.issuer_name, year=2026, month=9
)


def sample_registration(previous: PreviousRecord | None = None):
    return build_registration_record(
        invoice=INVOICE, software=SOFTWARE, previous=previous, generated_at=GENERATED_AT
    )


def sample_cancellation(previous: PreviousRecord | None = None):
    return build_cancellation_record(
        cancellation=CANCELLATION, software=SOFTWARE, previous=previous, generated_at=GENERATED_AT
    )


SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
WS = (
    "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/"
    "aplicaciones/es/aeat/tike/cont/ws"
)


def error(code: int, description: str) -> str:
    return f"""
    <tikR:CodigoErrorRegistro>{code}</tikR:CodigoErrorRegistro>
    <tikR:DescripcionErrorRegistro>{description}</tikR:DescripcionErrorRegistro>"""


REJECTION = error(1100, "Valor o tipo incorrecto del campo.")
DUPLICATE = error(3000, "Registro de facturación duplicado.") + """
    <tikR:RegistroDuplicado>
      <tik:IdPeticionRegistroDuplicado>20260924100005</tik:IdPeticionRegistroDuplicado>
      <tik:EstadoRegistroDuplicado>Correcta</tik:EstadoRegistroDuplicado>
    </tikR:RegistroDuplicado>"""
PRESENTATION = """
  <tikR:DatosPresentacion>
    <tik:NIFPresentador>12345678Z</tik:NIFPresentador>
    <tik:TimestampPresentacion>2026-09-24T10:00:05+02:00</tik:TimestampPresentacion>
  </tikR:DatosPresentacion>"""


def response_line(
    status: str,
    details: str = "",
    invoice_number: str = "A-2026/001",
    reference: str = "",
    issuer: str = "89890001K",
    operation: str = "Alta",
) -> str:
    reference = f"<tikR:RefExterna>{reference}</tikR:RefExterna>" if reference else ""
    return f"""
  <tikR:RespuestaLinea>
    <tikR:IDFactura>
      <tik:IDEmisorFactura>{issuer}</tik:IDEmisorFactura>
      <tik:NumSerieFactura>{invoice_number}</tik:NumSerieFactura>
      <tik:FechaExpedicionFactura>24-09-2026</tik:FechaExpedicionFactura>
    </tikR:IDFactura>
    <tikR:Operacion><tik:TipoOperacion>{operation}</tik:TipoOperacion></tikR:Operacion>{reference}
    <tikR:EstadoRegistro>{status}</tikR:EstadoRegistro>{details}
  </tikR:RespuestaLinea>"""


def response(status: str, *lines: str, presentation: str = "") -> bytes:
    return f"""<env:Envelope xmlns:env="{SOAP}"><env:Body>
<tikR:RespuestaRegFactuSistemaFacturacion
    xmlns:tikR="{WS}/RespuestaSuministro.xsd" xmlns:tik="{WS}/SuministroInformacion.xsd">
  <tikR:CSV>A-TEST-CSV</tikR:CSV>{presentation}
  <tikR:Cabecera><tik:ObligadoEmision>
    <tik:NombreRazon>Emisor de prueba SL</tik:NombreRazon><tik:NIF>89890001K</tik:NIF>
  </tik:ObligadoEmision></tikR:Cabecera>
  <tikR:TiempoEsperaEnvio>60</tikR:TiempoEsperaEnvio>
  <tikR:EstadoEnvio>{status}</tikR:EstadoEnvio>{"".join(lines)}
</tikR:RespuestaRegFactuSistemaFacturacion>
</env:Body></env:Envelope>""".encode()


STORED_DATA = """
      <r:RefExterna>ERP-1</r:RefExterna>
      <r:TipoFactura>F1</r:TipoFactura>
      <r:DescripcionOperacion>Servicios de consultoría</r:DescripcionOperacion>
      <r:CuotaTotal>21</r:CuotaTotal>
      <r:ImporteTotal>121</r:ImporteTotal>
      <r:Encadenamiento><r:PrimerRegistro>S</r:PrimerRegistro></r:Encadenamiento>
      <r:FechaHoraHusoGenRegistro>2026-09-24T10:00:00+02:00</r:FechaHoraHusoGenRegistro>
      <r:TipoHuella>01</r:TipoHuella>
      <r:Huella>58CCBA950FA5C4AAC62E16E7C871CBBE6374A0E1BA94BCCF6E55682F6B3726E1</r:Huella>"""
PRESENTED = """
    <r:DatosPresentacion>
      <tik:NIFPresentador>12345678Z</tik:NIFPresentador>
      <tik:TimestampPresentacion>2026-09-24T10:00:05+02:00</tik:TimestampPresentacion>
      <tik:IdPeticion>20260924100005</tik:IdPeticion>
    </r:DatosPresentacion>"""


def stored_error(code: int, description: str) -> str:
    return f"""
      <r:CodigoErrorRegistro>{code}</r:CodigoErrorRegistro>
      <r:DescripcionErrorRegistro>{description}</r:DescripcionErrorRegistro>"""


def stored_record(
    status: str = "Correcto",
    error: str = "",
    data: str = STORED_DATA,
    presentation: str = PRESENTED,
    invoice_number: str = "A-2026/001",
) -> str:
    return f"""
  <r:RegistroRespuestaConsultaFactuSistemaFacturacion>
    <r:IDFactura>
      <tik:IDEmisorFactura>89890001K</tik:IDEmisorFactura>
      <tik:NumSerieFactura>{invoice_number}</tik:NumSerieFactura>
      <tik:FechaExpedicionFactura>24-09-2026</tik:FechaExpedicionFactura>
    </r:IDFactura>
    <r:DatosRegistroFacturacion>{data}
    </r:DatosRegistroFacturacion>{presentation}
    <r:EstadoRegistro>
      <r:TimestampUltimaModificacion>2026-09-24T10:00:05+02:00</r:TimestampUltimaModificacion>
      <r:EstadoRegistro>{status}</r:EstadoRegistro>{error}
    </r:EstadoRegistro>
  </r:RegistroRespuestaConsultaFactuSistemaFacturacion>"""


def query_response(*records: str, next_page: str = "") -> bytes:
    key = next_page and f"""
  <r:ClavePaginacion>
    <tik:IDEmisorFactura>89890001K</tik:IDEmisorFactura>
    <tik:NumSerieFactura>{next_page}</tik:NumSerieFactura>
    <tik:FechaExpedicionFactura>24-09-2026</tik:FechaExpedicionFactura>
  </r:ClavePaginacion>"""
    return f"""<env:Envelope xmlns:env="{SOAP}"><env:Body>
<r:RespuestaConsultaFactuSistemaFacturacion
    xmlns:r="{WS}/RespuestaConsultaLR.xsd" xmlns:tik="{WS}/SuministroInformacion.xsd">
  <r:Cabecera>
    <tik:IDVersion>1.0</tik:IDVersion>
    <tik:ObligadoEmision>
      <tik:NombreRazon>Emisor de prueba SL</tik:NombreRazon><tik:NIF>89890001K</tik:NIF>
    </tik:ObligadoEmision>
  </r:Cabecera>
  <r:PeriodoImputacion><r:Ejercicio>2026</r:Ejercicio><r:Periodo>09</r:Periodo></r:PeriodoImputacion>
  <r:IndicadorPaginacion>{"S" if next_page else "N"}</r:IndicadorPaginacion>
  <r:ResultadoConsulta>{"ConDatos" if records else "SinDatos"}</r:ResultadoConsulta>
  {"".join(records)}{key}
</r:RespuestaConsultaFactuSistemaFacturacion>
</env:Body></env:Envelope>""".encode()
