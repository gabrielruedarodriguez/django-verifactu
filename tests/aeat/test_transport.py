import ssl

import httpx
import pytest
from lxml import etree

from django_verifactu.aeat.codes import SubmissionStatus
from django_verifactu.aeat.soap import AeatFault, NotDelivered, OutcomeUnknown, Refused
from django_verifactu.aeat.submission import build_submission
from django_verifactu.aeat.transport import client_ssl_context, post, send_submission
from tests.aeat.sample import INVOICE, SOAP, response, response_line, sample_registration
from tests.certificates import fake_pkcs12

SUBMISSION = build_submission(
    taxpayer_tax_id=INVOICE.issuer_tax_id,
    taxpayer_name=INVOICE.issuer_name,
    records=[sample_registration()],
)


def test_loads_a_password_protected_pkcs12():
    assert isinstance(client_ssl_context(fake_pkcs12(b"secret"), "secret"), ssl.SSLContext)


def test_wrong_password_is_rejected():
    with pytest.raises(ValueError):
        client_ssl_context(fake_pkcs12(b"secret"), "wrong")


@pytest.mark.parametrize(
    ("production", "seal_certificate", "host"),
    [
        (False, False, "prewww1.aeat.es"),
        (False, True, "prewww10.aeat.es"),
        (True, False, "www1.agenciatributaria.gob.es"),
        (True, True, "www10.agenciatributaria.gob.es"),
    ],
)
def test_posts_the_soap_envelope_to_the_official_endpoint(production, seal_certificate, host):
    requests = []

    def aeat(request):
        requests.append(request)
        return httpx.Response(200, content=response("Correcto", response_line("Correcto")))

    result = send_submission(
        SUBMISSION,
        ssl_context=ssl.create_default_context(),
        production=production,
        seal_certificate=seal_certificate,
        transport=httpx.MockTransport(aeat),
    )

    [request] = requests
    assert request.method == "POST"
    assert request.url == f"https://{host}/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP"
    assert request.headers["SOAPAction"] == '""'
    assert request.headers["Content-Type"] == "text/xml; charset=utf-8"
    body = etree.fromstring(request.content).find(f"{{{SOAP}}}Body")
    assert etree.QName(body[0]).localname == "RegFactuSistemaFacturacion"
    assert result.status is SubmissionStatus.ACCEPTED


def test_soap_fault_with_http_500_raises():
    fault = f"""<env:Envelope xmlns:env="{SOAP}"><env:Body><env:Fault>
<faultcode>env:Client</faultcode><faultstring>Codigo[4102].Error</faultstring>
</env:Fault></env:Body></env:Envelope>""".encode()
    with pytest.raises(AeatFault, match="4102"):
        send_submission(
            SUBMISSION,
            ssl_context=ssl.create_default_context(),
            production=False,
            seal_certificate=False,
            transport=httpx.MockTransport(lambda request: httpx.Response(500, content=fault)),
        )


def send_through(handler):
    return send_submission(
        SUBMISSION,
        ssl_context=ssl.create_default_context(),
        production=False,
        seal_certificate=False,
        transport=httpx.MockTransport(handler),
    )


def failing(error):
    def handler(request):
        raise error("boom", request=request)

    return handler


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
def test_requests_that_never_reached_the_aeat_can_be_sent_again(error):
    with pytest.raises(NotDelivered):
        send_through(failing(error))


def test_aeat_throttling_means_nothing_was_processed():
    busy = b"Error 429: Demasiadas peticiones - URL Desactivada Temporalmente"
    with pytest.raises(NotDelivered, match="429"):
        send_through(lambda request: httpx.Response(429, content=busy))


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout,
        httpx.ReadError,
        httpx.RemoteProtocolError,
        httpx.WriteTimeout,
        httpx.DecodingError,
    ],
)
def test_lost_answers_leave_the_outcome_unknown(error):
    with pytest.raises(OutcomeUnknown):
        send_through(failing(error))


def test_a_refused_certificate_means_nothing_was_processed():
    refusal = "https://sede.agenciatributaria.gob.es/Sede/errores/erro4011.html"
    with pytest.raises(Refused, match="erro4011"):
        send_through(lambda request: httpx.Response(302, headers={"location": refusal}))


def test_answers_that_are_not_soap_leave_the_outcome_unknown():
    gateway = b"<html><body>502 Bad Gateway</body></html>"
    with pytest.raises(OutcomeUnknown):
        send_through(lambda request: httpx.Response(502, content=gateway))


def test_post_returns_the_answer_as_it_came():
    answer = response("Correcto", response_line("Correcto"))
    content = post(
        SUBMISSION,
        ssl_context=ssl.create_default_context(),
        production=False,
        seal_certificate=False,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=answer)),
    )
    assert content == answer
