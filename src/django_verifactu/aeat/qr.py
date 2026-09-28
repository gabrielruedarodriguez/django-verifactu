import io
import math
from urllib.parse import urlencode

import segno
from lxml import etree

from django_verifactu.aeat.elements import RECORDS, tag

# Texts the AEAT requires above and below the QR code.
LABEL = "QR tributario:"
LEGEND = "Factura verificable en la sede electrónica de la AEAT"
SHORT_LEGEND = "VERI*FACTU"

_TEST_URL = "https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR"
_PRODUCTION_URL = "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR"
# The AEAT asks for 30-40 mm and at least 2 mm of quiet zone: these sizes meet both
# whether or not the quiet zone counts towards the 40 mm.
_SYMBOL_MM = 32
_QUIET_ZONE_MM = 3


# The values come from the built record: the QR must carry exactly what was registered.
def qr_url(record: etree._Element, *, production: bool) -> str:
    if record.tag != tag(RECORDS, "RegistroAlta"):
        raise ValueError("only registration records have a QR code")
    invoice = record.find(tag(RECORDS, "IDFactura"))
    query = urlencode(
        {
            "nif": invoice.findtext(tag(RECORDS, "IDEmisorFactura")),
            "numserie": invoice.findtext(tag(RECORDS, "NumSerieFactura")),
            "fecha": invoice.findtext(tag(RECORDS, "FechaExpedicionFactura")),
            "importe": record.findtext(tag(RECORDS, "ImporteTotal")),
        }
    )
    return f"{_PRODUCTION_URL if production else _TEST_URL}?{query}"


def qr_code(url: str) -> segno.QRCode:
    return segno.make_qr(url, error="m", boost_error=False)


def qr_svg(url: str) -> str:
    code = qr_code(url)
    module = _SYMBOL_MM / code.symbol_size(border=0)[0]
    border = math.ceil(_QUIET_ZONE_MM / module)
    image = io.BytesIO()
    code.save(
        image,
        kind="svg",
        xmldecl=False,
        nl=False,
        scale=module,
        border=border,
        unit="mm",
        dark="#000",
        light="#fff",
    )
    return image.getvalue().decode()
