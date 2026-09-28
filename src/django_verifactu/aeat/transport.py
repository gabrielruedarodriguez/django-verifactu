import ssl
import tempfile

import certifi
import httpx
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    NoEncryption,
    PrivateFormat,
    pkcs12,
)
from lxml import etree

from django_verifactu.aeat.domain import QueryPage, SubmissionResult
from django_verifactu.aeat.soap import (
    NotDelivered,
    OutcomeUnknown,
    Refused,
    parse_query_response,
    parse_response,
    wrap_in_envelope,
)

_PATH = "/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP"
_HOSTS = {
    (False, False): "prewww1.aeat.es",
    (False, True): "prewww10.aeat.es",
    (True, False): "www1.agenciatributaria.gob.es",
    (True, True): "www10.agenciatributaria.gob.es",
}
# The AEAT has taken more than 30 seconds to answer a large submission.
_TIMEOUT = httpx.Timeout(120, connect=10)
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def client_ssl_context(pkcs12_data: bytes, password: str) -> ssl.SSLContext:
    key, certificate, chain = pkcs12.load_key_and_certificates(pkcs12_data, password.encode())
    encryption = BestAvailableEncryption(password.encode()) if password else NoEncryption()
    pem = b"".join(
        [
            certificate.public_bytes(Encoding.PEM),
            *(extra.public_bytes(Encoding.PEM) for extra in chain),
            key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, encryption),
        ]
    )
    context = ssl.create_default_context(cafile=certifi.where())
    # ssl only loads client certificates from files: the key is written encrypted and
    # the file is deleted as soon as it has been read.
    with tempfile.NamedTemporaryFile(suffix=".pem") as file:
        file.write(pem)
        file.flush()
        context.load_cert_chain(file.name, password=password or None)
    return context


def send_submission(
    submission: etree._Element,
    *,
    ssl_context: ssl.SSLContext,
    production: bool,
    seal_certificate: bool,
    transport: httpx.BaseTransport | None = None,
) -> SubmissionResult:
    return parse_response(
        post(
            submission,
            ssl_context=ssl_context,
            production=production,
            seal_certificate=seal_certificate,
            transport=transport,
        )
    )


def send_query(
    query: etree._Element,
    *,
    ssl_context: ssl.SSLContext,
    production: bool,
    seal_certificate: bool,
    transport: httpx.BaseTransport | None = None,
) -> QueryPage:
    return parse_query_response(
        post(
            query,
            ssl_context=ssl_context,
            production=production,
            seal_certificate=seal_certificate,
            transport=transport,
        )
    )


def post(
    element: etree._Element,
    *,
    ssl_context: ssl.SSLContext,
    production: bool,
    seal_certificate: bool,
    transport: httpx.BaseTransport | None = None,
) -> bytes:
    url = f"https://{_HOSTS[production, seal_certificate]}{_PATH}"
    try:
        with httpx.Client(verify=ssl_context, transport=transport, timeout=_TIMEOUT) as client:
            response = client.post(
                url,
                content=wrap_in_envelope(element),
                headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""'},
            )
    except _NOT_SENT as error:
        raise NotDelivered(f"the AEAT could not be reached: {error}") from error
    except httpx.RequestError as error:
        raise OutcomeUnknown(f"the AEAT answer was lost: {error}") from error
    if response.status_code == 429:
        raise NotDelivered("the AEAT refuses requests for a while (HTTP 429)")
    if response.is_redirect:
        location = response.headers.get("location", "")
        raise Refused(f"the AEAT refused the certificate (HTTP {response.status_code} {location})")
    return response.content
