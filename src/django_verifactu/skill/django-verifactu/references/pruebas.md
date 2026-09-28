# Pruebas de una integración con django-verifactu

Lee este archivo cuando escribas tests de un proyecto que usa django-verifactu: tests unitarios de emisión, QR y avisos (con `pytest-django` o `django.test.TestCase`), tests de la remisión con una AEAT falsa y tests extremo a extremo contra el entorno de pruebas de la AEAT. La configuración está en references/configuracion.md y la remisión, en references/envio.md.

## Trampas

1. **Nunca pongas `PRODUCTION = True` en tests ni en CI.** Lo que se remite a producción son facturas reales. Preguntas frecuentes para desarrolladores de la AEAT (versión 1.3, 4-12-2025, apartado 11): «las facturas de prueba o facturas de formación, elaboradas con un SIF adaptado, siempre que lleguen a ser facturas propiamente hablando (es decir que se generen de forma real, y que no sean simples borradores o prefacturas no confirmadas), deben ser tratadas como si de facturas reales se tratara a los efectos del RD 1007/23 y resto de normativa de desarrollo», y de ellas «deberá procederse a la inmediata posterior anulación».
2. **`register`, `amend` y `cancel` necesitan una transacción abierta.** Un test con `@pytest.mark.django_db` o `TestCase` ya corre dentro de una. Con `django_db(transaction=True)` o `TransactionTestCase`, sin `transaction.atomic()` lanzan `TransactionManagementError`. Envuélvelos siempre en `transaction.atomic()`, como en tu código.
3. **`send_pending()` nunca va dentro de `transaction.atomic()`**: en cuanto hay registros que remitir, lanza `RuntimeError`. Llámalo directamente en el cuerpo del test; dentro de `TestCase` o `django_db` funciona.
4. **Nada llega a la AEAT si no llamas a `send_pending()`** (o a `verifactu_send`). Emitir nunca contacta con la AEAT, así que en un test unitario todos los registros quedan `pending`.
5. **`record_created` y `alarm_raised` se envían tras el commit.** Dentro de `TestCase` o `django_db` no hay commit: usa `captureOnCommitCallbacks(execute=True)` o la fixture `django_capture_on_commit_callbacks`. `record_answered` y `submission_finished` los envía `send_pending()` directamente.
6. **No fabriques registros ni respuestas a mano.** `Record`, `Installation`, `Submission` y `SubmissionLine` lanzan `ImmutableRecord` en `save()`, `delete()`, `create()` y `update()`. Crea registros con `register` y respuestas con la AEAT falsa de abajo. No uses nombres que empiezan por `_` (como `Record._writes`), aunque los tests de la propia librería lo hagan.
7. **Un objeto con registros no se puede borrar** (`ProtectedError`), ni en el código del test ni en cascada.

## Tests unitarios

En los settings de tests, parte de los reales y fuerza el entorno de pruebas. Emitir no necesita credenciales, así que basta con `TAXPAYERS` vacío: `VERIFACTU = {**VERIFACTU, "PRODUCTION": False, "TAXPAYERS": {}}`.

`Sale` es tu modelo con `verifactu_records = VerifactuRecords()`. Usa una fecha de expedición pasada: una futura falla la validación (1112).

```python
# tests/test_invoicing.py
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from django.db import transaction

from billing.models import Sale
from django_verifactu.aeat.domain import Cancellation, Invoice, Party, TaxLine
from django_verifactu.aeat.violations import ValidationError
from django_verifactu.issuing import AlreadyRegistered, amend, cancel, register
from django_verifactu.notices import notices
from django_verifactu.qr import qr_url
from django_verifactu.verifying import verify

pytestmark = pytest.mark.django_db

INVOICE = Invoice(
    issuer_tax_id="B12345674",
    issuer_name="Acme SL",
    invoice_number="A-2026/001",
    issue_date=date(2026, 9, 1),
    description="Servicios de consultoría",
    recipients=(Party("Cliente", tax_id="12345678Z"),),
    lines=(TaxLine(base=Decimal("100"), rate=Decimal("21"), tax=Decimal("21")),),
)


def invoice(number, **changes):
    return replace(INVOICE, invoice_number=number, **changes)


def issue(number, **changes):
    with transaction.atomic():
        return register(Sale.objects.create(number=number), invoice(number, **changes))


def test_registering_writes_a_pending_record():
    record = issue("A-2026/001")
    assert (record.status, record.position) == ("pending", 1)
    assert qr_url(record.content_object).startswith("https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR?")
    assert notices() == [] and verify() == []


def test_invalid_invoices_are_refused_before_writing():
    with pytest.raises(ValidationError) as error:
        issue("A-2026/002", description="")
    assert [violation.code for violation in error.value.violations] == [1100]


def test_amend_and_cancel():
    sale = issue("A-2026/003").content_object
    with pytest.raises(AlreadyRegistered), transaction.atomic():
        register(sale, invoice("A-2026/003"))
    with transaction.atomic():
        amended = amend(sale, invoice("A-2026/003", description="Consultoría de septiembre"))
        cancelled = cancel(sale, Cancellation("B12345674", "A-2026/003", date(2026, 9, 1)))
    assert amended.amendment and cancelled.operation == "Anulacion"
    assert [r.status for r in sale.verifactu_records.all()] == ["pending"] * 3
```

Con `TestCase`, en el mismo módulo:

```python
from django.test import TestCase


class InvoicingTests(TestCase):
    def test_record_created_is_sent_on_commit(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            issue("A-2026/004")
        self.assertEqual(len(callbacks), 1)  # record_created
```

`notices()` es una lista vacía mientras nada falla. También avisa de los registros que llevan más de 240 s pendientes: si tu test adelanta el reloj, aparecerán.

## Una AEAT falsa

`send_pending()` llama a dos nombres del módulo `django_verifactu.sending`, y son los que se sustituyen (sustituirlos en `django_verifactu.aeat.transport` no tiene efecto):

- `post(element, *, ssl_context, production, seal_certificate)` recibe el envío `RegFactuSistemaFacturacion` como elemento de lxml, sin el sobre SOAP, y devuelve los bytes de la respuesta.
- `client_ssl_context(certificate, password)` crea el contexto TLS a partir del PKCS#12. Sustitúyelo para que unos bytes cualesquiera sirvan de certificado.

Las credenciales se siguen leyendo, así que la fixture añade el obligado tributario a `TAXPAYERS`:

```python
# tests/conftest.py
import pytest
from lxml import etree
from lxml.builder import ElementMaker

from django_verifactu import sending

WS = (
    "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/"
    "aplicaciones/es/aeat/tike/cont/ws/"
)
SOAP = ElementMaker(namespace="http://schemas.xmlsoap.org/soap/envelope/")
R = ElementMaker(namespace=WS + "RespuestaSuministro.xsd")
T = ElementMaker(namespace=WS + "SuministroInformacion.xsd")


class FakeAeat:
    def __init__(self):
        self.answers = {}  # NumSerieFactura -> (EstadoRegistro, código, descripción)
        self.failure = None  # p. ej. NotDelivered("sin conexión")
        self.wait_seconds = 0  # la AEAT real responde 60

    def __call__(self, element, **kwargs):
        if self.failure:
            raise self.failure
        lines = []
        for record in element.iterfind(".//{*}RegistroFactura/*"):
            issuer, number, issued = (child.text for child in record.find("{*}IDFactura"))
            operation = "Alta" if etree.QName(record).localname == "RegistroAlta" else "Anulacion"
            status, code, text = self.answers.get(number, ("Correcto", None, None))
            error = []
            if code:
                error = [R.CodigoErrorRegistro(str(code)), R.DescripcionErrorRegistro(text)]
            lines.append(
                R.RespuestaLinea(
                    R.IDFactura(
                        T.IDEmisorFactura(issuer),
                        T.NumSerieFactura(number),
                        T.FechaExpedicionFactura(issued),
                    ),
                    R.Operacion(T.TipoOperacion(operation)),
                    R.EstadoRegistro(status),
                    *error,
                )
            )
        answer = R.RespuestaRegFactuSistemaFacturacion(
            R.CSV("CSV-DE-PRUEBA"),
            R.TiempoEsperaEnvio(str(self.wait_seconds)),
            R.EstadoEnvio("Correcto"),
            *lines,
        )
        return etree.tostring(SOAP.Envelope(SOAP.Body(answer)))


@pytest.fixture
def aeat(monkeypatch, settings):
    fake = FakeAeat()
    monkeypatch.setattr(sending, "post", fake)
    monkeypatch.setattr(sending, "client_ssl_context", lambda certificate, password: None)
    settings.VERIFACTU = {
        **settings.VERIFACTU,
        "TAXPAYERS": {
            "B12345674": {"name": "Acme SL", "certificate": b"no-es-un-p12", "password": "x"}
        },
    }
    return fake
```

Lo que debe contener una respuesta falsa para que se guarde:

- Un sobre SOAP 1.1 con `Body` y, dentro, `RespuestaRegFactuSistemaFacturacion` del espacio de nombres `RespuestaSuministro.xsd`, con `TiempoEsperaEnvio` (entero), `EstadoEnvio` (`Correcto`, `ParcialmenteCorrecto` o `Incorrecto`) y, opcional, `CSV`.
- Una `RespuestaLinea` por registro, en el orden del envío, con `IDFactura` (`IDEmisorFactura`, `NumSerieFactura` y `FechaExpedicionFactura` en `dd-mm-aaaa`, del espacio `SuministroInformacion.xsd`, también para una anulación), `Operacion/TipoOperacion` (`Alta` o `Anulacion`), `EstadoRegistro` (`Correcto`, `AceptadoConErrores` o `Incorrecto`) y, opcionales, `CodigoErrorRegistro` y `DescripcionErrorRegistro`.
- Si falta un elemento obligatorio o un valor no es válido, el envío queda `unknown`. Si una línea no coincide con su registro en NIF, número, fecha u operación, se ignora. En ambos casos el registro sigue `pending`.

Para los fallos, haz que el doble lance las excepciones de `django_verifactu.aeat.soap`: `NotDelivered` deja el envío `not_delivered`, `OutcomeUnknown` lo deja `unknown` y `Refused` lo deja `fault`. Una respuesta con `Fault` y `faultstring` `Codigo[4102]...` lo deja `fault` con `error_code = 4102`. Cualquier otra excepción del doble también acaba en `fault`, con la traza en el log `django_verifactu`. En todos los casos los registros siguen `pending`.

En el mismo módulo que los tests unitarios:

```python
from datetime import timedelta

from django.utils import timezone

from django_verifactu.aeat.soap import NotDelivered
from django_verifactu.sending import send_pending


def test_the_aeat_answers_are_stored(aeat):
    census = "El NIF del bloque Destinatarios no está identificado en el censo de la AEAT."
    aeat.answers["A-2026/011"] = ("AceptadoConErrores", 2001, census)
    aeat.answers["A-2026/012"] = ("Incorrecto", 1239, "Error en el bloque Destinatario.")
    records = [issue(number) for number in ("A-2026/010", "A-2026/011", "A-2026/012")]
    [submission] = send_pending()
    for record in records:
        record.refresh_from_db()
    assert submission.outcome == "answered"
    assert [r.status for r in records] == ["accepted", "accepted_with_errors", "rejected"]
    assert records[1].needs_amendment and records[2].error_code == 1239


def test_unsent_records_stay_pending_and_are_retried(aeat, monkeypatch):
    aeat.failure = NotDelivered("sin conexión")
    record = issue("A-2026/020")
    [failed] = send_pending()
    assert failed.outcome == "not_delivered"
    assert [notice.taxpayer_tax_id for notice in notices()] == ["B12345674"]
    aeat.failure = None
    assert send_pending() == []  # tras un fallo espera al menos un minuto
    later = timezone.now() + timedelta(seconds=61)
    monkeypatch.setattr(timezone, "now", lambda: later)
    [resent] = send_pending()
    record.refresh_from_db()
    assert (resent.incident, record.status) == (True, "accepted")
```

- Con `wait_seconds = 0` cada `send_pending()` remite en el acto. Con 60, como la AEAT real, una segunda pasada devuelve `[]` hasta que pasan 60 s: adelanta `django.utils.timezone.now` como arriba.
- El remitente guarda en caché el contexto TLS de cada par de certificado y contraseña durante la vida del proceso. Usa en la AEAT falsa bytes que no sean tu certificado real, para que un contexto falso nunca llegue a un test contra la AEAT del mismo proceso.
- La AEAT falsa no cubre `verify(aeat=True)` ni `django_verifactu.querying.query()`, que consultan a la AEAT por otro camino: pruébalos solo contra el entorno de pruebas.

## Contra el entorno de pruebas de la AEAT

Estos tests contactan con el entorno de pruebas de la AEAT. Márcalos para que se salten sin credenciales:

```python
# tests/test_aeat.py
import os
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction

from billing.models import Sale
from django_verifactu.aeat.domain import Invoice, Party, TaxLine
from django_verifactu.issuing import register
from django_verifactu.sending import send_pending

CERTIFICATE = os.environ.get("AEAT_TEST_CERTIFICATE")  # ruta al .p12, fuera del repositorio
PASSWORD = os.environ.get("AEAT_TEST_PASSWORD")
NIF = os.environ.get("AEAT_TEST_NIF")  # el NIF del titular del certificado
NAME = os.environ.get("AEAT_TEST_NAME")

requires_aeat = pytest.mark.skipif(
    not (CERTIFICATE and PASSWORD and NIF and NAME),
    reason="define AEAT_TEST_* para llamar al entorno de pruebas de la AEAT",
)


@requires_aeat
@pytest.mark.django_db
def test_the_aeat_accepts_an_invoice(settings):
    settings.VERIFACTU = {
        **settings.VERIFACTU,
        "PRODUCTION": False,
        "TAXPAYERS": {NIF: {"name": NAME, "certificate": CERTIFICATE, "password": PASSWORD}},
    }
    now = datetime.now(ZoneInfo("Europe/Madrid"))
    number = f"PRUEBA-{now:%Y%m%d%H%M%S}"
    with transaction.atomic():
        record = register(
            Sale.objects.create(number=number),
            Invoice(
                issuer_tax_id=NIF,
                issuer_name=NAME,
                invoice_number=number,
                issue_date=now.date(),
                description="Prueba de integración",
                recipients=(Party(NAME, tax_id=NIF),),
                lines=(TaxLine(base=Decimal("100"), rate=Decimal("21"), tax=Decimal("21")),),
            ),
        )
    [submission] = send_pending()  # llama al entorno de pruebas de la AEAT
    record.refresh_from_db()
    assert (submission.outcome, record.status) == ("answered", "accepted"), submission.response
```

Comportamientos verificados en el entorno de pruebas que condicionan estos tests:

- **Certificado real.** Un certificado autofirmado o caducado recibe una redirección HTTP 302 a `erro4011.html`: el envío queda `fault`. Usa como obligado tributario al titular del certificado.
- **Productor censado.** Si el NIF de `SOFTWARE["producer"]` no está en el censo, cada registro se rechaza con 1110.
- **Números únicos por ejecución.** El entorno de pruebas conserva lo que recibe: repetir una factura ya remitida se responde con 3000 (registro duplicado).
- **Destinatarios reales.** El propio titular del certificado como destinatario se acepta. Un destinatario con identificador `07` (no censado), país `ES` y un DNI que no está en el censo da 2001 (aceptado con errores), y un NIF-IVA que no está en VIES, 1239 (rechazado).
- **Reloj real.** No adelantes `timezone.now` en estos tests: un registro generado a más de 240 s del reloj de la AEAT se acepta con el error 2004.
- **Cadena nueva en cada base de datos de tests.** Empieza con `PrimerRegistro` y un número de instalación nuevo, y la AEAT la acepta.
- **Pocos envíos.** La base de datos de tests se vacía entre tests, así que el control de flujo no recuerda los envíos de tests anteriores. Tras un día de uso intenso, la AEAT respondió HTTP 429 (el envío queda `not_delivered`). Haz un solo `send_pending()` por test y pocos tests.
- **QR.** Con `PRODUCTION = False`, `qr_url` apunta a `https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR`, pública y sin certificado, con un límite diario de consultas.

Lo que el entorno de pruebas no demuestra:

- El control de flujo: aceptó envíos seguidos sin esperar `TiempoEsperaEnvio`. Pruébalo con la AEAT falsa y `wait_seconds = 60`.
- Los certificados de sello (`seal: True`) y la remisión por un tercero con apoderamiento: no se han verificado.
- La existencia de los acuerdos de facturación: aceptó `NumRegistroAcuerdoFacturacion` e `IdAcuerdoSistemaInformatico` inexistentes.
- Producción: la librería solo se ha validado contra el entorno de pruebas.
