from lxml import etree

from django_verifactu.aeat.domain import Party

_WS = (
    "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/"
    "aplicaciones/es/aeat/tike/cont/ws/"
)
RECORDS = _WS + "SuministroInformacion.xsd"
SUBMISSION = _WS + "SuministroLR.xsd"
RESPONSE = _WS + "RespuestaSuministro.xsd"
QUERY = _WS + "ConsultaLR.xsd"
QUERY_RESPONSE = _WS + "RespuestaConsultaLR.xsd"
SOAP = "http://schemas.xmlsoap.org/soap/envelope/"


def tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def add(
    parent: etree._Element, namespace: str, name: str, text: str | None = None
) -> etree._Element:
    element = etree.SubElement(parent, tag(namespace, name))
    element.text = text
    return element


def add_party(element: etree._Element, party: Party) -> None:
    add(element, RECORDS, "NombreRazon", party.name)
    if party.tax_id is not None:
        add(element, RECORDS, "NIF", party.tax_id)
        return
    foreign = add(element, RECORDS, "IDOtro")
    if party.foreign_id.country is not None:
        add(foreign, RECORDS, "CodigoPais", party.foreign_id.country)
    add(foreign, RECORDS, "IDType", party.foreign_id.id_type)
    add(foreign, RECORDS, "ID", party.foreign_id.number)
