# django-verifactu

VERI*FACTU para Django. Mantiene los registros de facturación encadenados que exige la Agencia Tributaria (AEAT), los remite a la AEAT, imprime el código QR de la factura y verifica que tu base de datos y la AEAT coinciden.

Tus facturas siguen en tus propios modelos. django-verifactu solo guarda la evidencia de VERI*FACTU (instalaciones, registros, envíos y respuestas de la AEAT), la escribe dentro de transacciones que controla y no permite que nada más la modifique.

Cada comportamiento de la AEAT en el que se apoya se ha comprobado contra el entorno de pruebas de la AEAT.

## Responsabilidad

django-verifactu es software libre y gratuito, distribuido «tal cual» (*as is*), sin garantía de ningún tipo, tampoco de cumplimiento fiscal, y sin responsabilidad por los daños que cause su uso, salvo lo que exija la ley aplicable, conforme a la licencia Apache 2.0 (secciones 7 y 8).

django-verifactu es un componente que se integra en un sistema informático de facturación, no un sistema completo. El sistema de facturación es el software que construyes con él y que identificas en `VERIFACTU["SOFTWARE"]`. Su productor debe emitir la declaración responsable (RD 1007/2023, art. 13) y, en palabras de la AEAT, cuando utiliza código abierto «se hará responsable del funcionamiento del mismo, incluyendo los sistemas de seguridad exigidos» (preguntas frecuentes sobre la certificación de los sistemas informáticos de facturación). Comprueba que tu sistema cumple la normativa y consulta a un asesor para tu caso.

La librería se ha validado únicamente contra el entorno de pruebas de la AEAT.

## Alcance

- Solo VERI*FACTU. La modalidad NO VERI*FACTU (registros firmados, registro de eventos, requerimientos) no está soportada.
- Una cadena por obligado tributario y entorno, y una zona horaria por despliegue.

## Requisitos

- Python 3.11 o posterior y Django 5.2 o posterior, con `USE_TZ = True`.
- Se recomienda PostgreSQL. MySQL funciona con el aislamiento READ COMMITTED que Django usa por defecto, y SQLite sirve para desarrollo.
- Un certificado cualificado (PKCS#12) por obligado tributario, o de un representante autorizado a actuar en su nombre.

## Instalación

```console
pip install django-verifactu
```

```python
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    # ...
    "django_verifactu",
]
```

```console
python manage.py migrate
```

## Configuración

```python
import os
from datetime import date

from django_verifactu.aeat.domain import Party

VERIFACTU = {
    # Obligatorio: False remite al entorno de pruebas de la AEAT, True a producción.
    "PRODUCTION": False,
    # Tu sistema de facturación, tal como lo declaras ante la AEAT.
    "SOFTWARE": {
        "producer": Party("Acme Software SL", tax_id="B12345674"),
        "name": "AcmeERP",
        "system_id": "AE",
        "version": "4.2.0",
        "multiple_taxpayers_possible": False,
    },
    # Los obligados tributarios cuyas facturas remites, por NIF.
    "TAXPAYERS": {
        "B12345674": {
            "name": "Acme SL",
            "certificate": "/run/secrets/acme.p12",  # una ruta, o el contenido del fichero en bytes
            "password": os.environ["ACME_P12_PASSWORD"],
            # Opcionales:
            # "seal": True,                           # un certificado de sello
            # "representative": Party("Gestoría SL", tax_id="..."),
            # "verifactu_end_date": date(2026, 12, 31),  # renuncia a VERI*FACTU
        },
    },
    # Opcionales, ver más abajo.
    # "MULTIPLE_TAXPAYERS": "myapp.verifactu.several_billings",
    # "TIME_ZONE": "Europe/Madrid",
}
```

- **`SOFTWARE`**: `name` tiene como máximo 30 caracteres, `system_id` dos letras mayúsculas o dígitos, y `version` como máximo 50 caracteres.
- **`TAXPAYERS`**: también puede ser la ruta con puntos de una función `(tax_id) -> Taxpayer | None`, para credenciales guardadas en una base de datos o un almacén de secretos. `Taxpayer` es `django_verifactu.conf.Taxpayer`, con los mismos campos que las entradas de arriba.
- **Las credenciales solo se necesitan para remitir.** Las facturas se emiten aunque se esté renovando un certificado, y sus registros esperan a que vuelva a funcionar.
- **`IndicadorMultiplesOT`**: vale `S` cuando `TAXPAYERS` incluye más de un NIF, o cuando la base de datos contiene la cadena de otro obligado tributario en el mismo entorno. En ese caso `SOFTWARE["multiple_taxpayers_possible"]` debe ser `True`; si no, emitir lanza `ImproperlyConfigured`. En un SaaS, la AEAT cuenta en cambio las facturaciones de cada usuario (preguntas frecuentes para desarrolladores, apartado 4). Apunta `MULTIPLE_TAXPAYERS` a una función `(tax_id) -> bool` que haga ese cálculo.
- **`TIME_ZONE`**: los registros se fechan en esta zona (por defecto `Europe/Madrid`), nunca en la zona activa de la petición.

`manage.py check` informa de los problemas de configuración:

| Id | Problema |
|----|----------|
| `django_verifactu.E001` | `USE_TZ` no es `True` |
| `django_verifactu.E002` | Falta `PRODUCTION` o no es un booleano |
| `django_verifactu.E003` | `SOFTWARE` o `TIME_ZONE` no son válidos, o `SOFTWARE` declara un único obligado tributario y `TAXPAYERS` incluye más |
| `django_verifactu.E004` | `TAXPAYERS` no es un diccionario, o su función no se puede importar |
| `django_verifactu.E005` | `MULTIPLE_TAXPAYERS` no se puede importar |
| `django_verifactu.W001` | Una entrada de `TAXPAYERS` no se puede usar (certificado, contraseña, NIF, nombre, representante, fecha de fin) o su certificado ha caducado |

`django_verifactu.W001` es un aviso para que un obligado tributario nunca impida remitir los registros de los demás.

## Vincular tus facturas

Añade un campo `VerifactuRecords` a cada modelo cuyos objetos tengan registros. No necesita migración.

```python
from django.db import models
from django_verifactu.models import VerifactuRecords


class Sale(models.Model):
    number = models.CharField(max_length=60)
    verifactu_records = VerifactuRecords()
```

Un objeto que tiene registros no se puede borrar, ni siquiera en cascada.

## Emitir

Llama a `register`, `amend` y `cancel` dentro de una transacción, la misma que guarda la factura. Fuera de una transacción lanzan `TransactionManagementError`.

```python
from datetime import date
from decimal import Decimal

from django.db import transaction
from django_verifactu.aeat.domain import Invoice, Party, TaxLine
from django_verifactu.issuing import register

with transaction.atomic():
    sale = Sale.objects.create(number="A-2026/001")
    record = register(
        sale,
        Invoice(
            issuer_tax_id="B12345674",
            issuer_name="Acme SL",
            invoice_number="A-2026/001",
            issue_date=date(2026, 9, 28),
            description="Servicios de consultoría",
            recipients=(Party("Cliente", tax_id="12345678Z"),),
            lines=(TaxLine(base=Decimal("100"), rate=Decimal("21"), tax=Decimal("21")),),
        ),
    )
```

`Invoice`, `TaxLine`, `Party`, `ForeignId`, `InvoiceId`, `CorrectedAmounts` y `Cancellation`, en `django_verifactu.aeat.domain`, cubren los tipos de factura, desgloses, terceros y generadores que acepta la AEAT, salvo la cuota de recargo rectificada de una factura rectificativa (`CuotaRecargoRectificado`). Sus listas de códigos (`InvoiceType`, `CorrectionType`, `TaxType`, `RegimeKey`...) están en `django_verifactu.aeat.codes`.

Una factura que incumple las reglas de validación de la AEAT lanza `django_verifactu.aeat.violations.ValidationError`, cuyas `violations` llevan los códigos de error de la propia AEAT. Las comprobaciones que necesitan datos de la AEAT (el censo, VIES, facturas que ya tiene) solo llegan en su respuesta: como un registro `rejected`, o como `accepted_with_errors` (por ejemplo 2001, un destinatario que no está en el censo), que `record.needs_amendment` señala.

Cómo corregir una factura depende del error, no de si su registro fue aceptado o rechazado (preguntas frecuentes para desarrolladores, apartado 17):

- **Errores previstos en el Reglamento por el que se regulan las obligaciones de facturación (ROF)**, como un importe, un tipo o un destinatario incorrectos: expide una factura rectificativa (R1 a R5). Es una factura nueva, con su propio objeto, que se remite con `register`.
- **Otros errores en datos del registro que no aparecen en la factura impresa**: llama a `amend` con la factura corregida completa (una *subsanación*).
- **Una factura que nunca debió expedirse**: anúlala con `cancel`.

Pasa el objeto de la propia factura:

```python
from django_verifactu.aeat.domain import Cancellation
from django_verifactu.issuing import amend, cancel

with transaction.atomic():
    amend(sale, corrected_invoice)

with transaction.atomic():
    cancel(sale, Cancellation("B12345674", "A-2026/001", date(2026, 9, 28)))
```

La librería decide los indicadores del ciclo de vida (`Subsanacion`, `RechazoPrevio`, `SinRegistroPrevio`) a partir de los registros que ya tiene de esa factura, así que nunca los indicas tú. Lanza:

- `AlreadyRegistered` cuando la factura ya está registrada, se haya remitido o no: subsánala en su lugar.
- `AlreadyCancelled` cuando ya está anulada.
- `LifecycleError` cuando la factura pertenece a otro objeto, o el objeto ya tiene otra factura.

Cada `Record` conserva su XML inalterable, su huella y la respuesta de la AEAT: `status` (`pending`, `accepted`, `accepted_with_errors` o `rejected`), `error_code` y `error_description`. `record.needs_amendment` indica si un registro aceptado todavía debe corregirse.

## Remitir

Ejecuta el remitente como un servicio permanente (systemd, un contenedor, un supervisor):

```console
python manage.py verifactu_send --loop
```

Sin `--loop` hace una sola pasada. `--interval` fija los segundos entre pasadas (5) y `--taxpayer NIF` remite un único obligado tributario. Los registros deben remitirse de inmediato (RD 1007/2023, art. 16), así que si usas cron o tu propio planificador con `django_verifactu.sending.send_pending()`, ejecuta una pasada cada minuto.

El remitente:

- respeta el tiempo de espera de la AEAT entre envíos, o remite en cuanto hay 1000 registros pendientes (Orden HAC/1177/2024, art. 16.2);
- tras un fallo, espera de 1 a 15 minutos y reintenta, dentro del reintento horario del art. 16.4;
- declara la incidencia (`Incidencia`) cuando reenvía registros cuyo intento anterior no obtuvo respuesta;
- recupera los envíos cuya respuesta se perdió sin duplicar nada;
- nunca deja que el problema de un obligado tributario (un certificado rechazado, una contraseña errónea) detenga a los demás.

Señales, todas enviadas después del commit de la transacción:

- `django_verifactu.signals.record_created(record)`
- `django_verifactu.signals.record_answered(record, line)`
- `django_verifactu.signals.submission_finished(submission)`
- `django_verifactu.signals.alarm_raised(installation, problems)`, ver más abajo.

## Avisos y alarmas

La Orden HAC/1177/2024 exige que el sistema muestre dos tipos de avisos, y tus usuarios deben verlos:

- **Registros sin remitir (art. 16.4)**: desde un fallo hasta que se remiten todos, cuántos registros no se han podido remitir. Se consideran sin remitir cuando un envío ha fallado, o cuando llevan esperando más de lo que tolera la AEAT, sea cual sea la causa (por ejemplo, un remitente que no se está ejecutando).
- **Problemas en la cadena (arts. 6.f, 7.i y 7.j)**: antes de emitir cada registro, la librería comprueba que el último registro está correctamente encadenado y que su fecha no es más de un minuto posterior a la hora actual. Un problema nunca detiene la facturación: el registro se emite, el problema se anota como error en el log y se envía `alarm_raised`.

Muestra los avisos donde trabajan tus usuarios:

```django
{% load verifactu %}
{% verifactu_notices %}
{% verifactu_notices request.user.company.nif %}
```

Sin argumento, la etiqueta muestra los avisos de todos los obligados tributarios, lo que conviene a los operadores. Con uno, muestra solo los de ese obligado tributario, y ninguno si el valor está vacío, de modo que un usuario cuya empresa aún no tiene NIF nunca ve los de otro. La plantilla `django_verifactu/notices.html` se puede sobrescribir.

`django_verifactu.notices.notices(taxpayer_tax_id=None)` devuelve la misma lista, cada aviso con su `taxpayer_tax_id`, su `message` en inglés y, en los avisos de registros sin remitir, su número en `unsent`, para redactarlo en tu idioma al sobrescribir la plantilla. El admin los muestra encima de sus listados. Cuestan unas pocas consultas por obligado tributario. Los problemas de cadena se buscan en los 20 registros más recientes de cada cadena; `verifactu_verify` comprueba las cadenas completas.

## Imprimir el código QR

```django
{% load verifactu %}
{% verifactu_qr sale %}
```

Imprime el texto «QR tributario:», el código QR en SVG (un código de 32 mm dentro de una zona de silencio de al menos 3 mm, unos 38 a 40 mm en total) y la leyenda que exige la AEAT. Sobrescribe la plantilla `django_verifactu/qr.html` para cambiar la maquetación.

Para PDF, `django_verifactu.qr.qr_url(sale)` devuelve la URL, y `django_verifactu.aeat.qr.qr_svg(url)` o `qr_code(url)` (un código QR de segno) la dibujan.

El código QR sale del último registro de alta que no fue rechazado, así que sigue a las subsanaciones. Una factura anulada conserva su código QR para reimpresiones. Un objeto sin registro de alta lanza `NotRegistered`.

## Admin

Con `django.contrib.admin` instalado, las instalaciones, los registros y los envíos aparecen en modo de solo lectura. Para mostrar los registros en las páginas de tus facturas:

```python
from django.contrib import admin
from django_verifactu.admin import RecordInline


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    inlines = [RecordInline]
```

## Verificar

```console
python manage.py verifactu_verify
python manage.py verifactu_verify --aeat
```

Sin opciones comprueba en local cada cadena: registros que faltan o están fuera de lugar, huellas que ya no coinciden con su XML, columnas que no coinciden con él, eslabones rotos y registros fechados más de un minuto antes que el anterior. La huella solo cubre los campos que la AEAT incluye en ella (emisor, número, fecha de expedición, tipo, totales, encadenamiento y fecha y hora de generación), así que los cambios en el resto del XML, como la descripción, no se detectan. Con `--aeat` compara además cada factura con lo que tiene la AEAT, mes a mes, e informa de:

- registros aceptados aquí que la AEAT no tiene;
- otro registro, de este sistema o de otro, en la AEAT;
- facturas de esta instalación que la AEAT tiene y la base de datos no, como tras restaurar una copia de seguridad.

Termina con error cuando encuentra un problema. `django_verifactu.verifying.verify()` devuelve la misma lista, y `django_verifactu.querying.query()` ejecuta cualquier consulta a la AEAT con las credenciales configuradas.

## Reiniciar una cadena

Después de restaurar una copia de seguridad de la base de datos, o cuando cambia `SOFTWARE["system_id"]`, inicia una cadena nueva para el obligado tributario:

```console
python manage.py verifactu_new_installation B12345674
```

Los siguientes registros reciben un nuevo número de instalación y empiezan con `PrimerRegistro`. Los registros pendientes de la cadena anterior se siguen remitiendo primero.

## Integrar con un agente de IA

django-verifactu incluye una [Agent Skill](https://agentskills.io) que enseña a los agentes de programación a integrarla: las reglas que no se pueden romper, el flujo de integración, cómo corregir cada tipo de error, las pruebas y los requisitos legales, con las citas de la normativa. Instálala en tu proyecto en cuanto añadas `django_verifactu` a `INSTALLED_APPS`, antes de configurar `VERIFACTU`:

```console
python manage.py verifactu_skill
```

El comando la copia en `.agents/skills/django-verifactu`, que leen Codex, Cursor, Gemini CLI, GitHub Copilot, OpenCode y otros, y en `.claude/skills/django-verifactu` para Claude Code. Usa `--agent kiro` para Kiro y `--path` si el proyecto no es la raíz del repositorio git.

La skill describe la versión instalada de la librería. Vuelve a ejecutar el comando al actualizarla; `python manage.py verifactu_skill --check` falla si la copia está desactualizada, por ejemplo en la integración continua. El comando reemplaza solo sus propias carpetas.

La skill ayuda, pero no sustituye tu revisión: tú respondes del sistema de facturación que construyes.

## El núcleo de la AEAT

`django_verifactu.aeat` no depende de Django. Construye y valida registros, envíos y consultas, calcula huellas y códigos QR, y se comunica con los servicios web de la AEAT.

## Desarrollo

```console
uv run pytest
uv run ruff check
```

- `VERIFACTU_TEST_POSTGRES=postgres://usuario:contraseña@host:puerto/nombre` ejecuta la batería de tests, incluidos los de concurrencia, sobre PostgreSQL.
- `VERIFACTU_TEST_CERTIFICATE` y `VERIFACTU_TEST_PASSWORD_FILE` ejecutan además los tests que llaman al entorno de pruebas de la AEAT, con ese certificado.

## Licencia

Apache-2.0. Copyright 2026 Gabriel Rueda Rodriguez.
