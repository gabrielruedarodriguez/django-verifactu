# Errores: excepciones, estados y códigos de la AEAT

Lee este archivo cuando `register`, `amend`, `cancel` u otra llamada de django-verifactu lance una excepción, cuando un `Record` quede `rejected` o `accepted_with_errors`, o cuando un `Submission` termine en `fault`. Explica cuándo ocurre cada excepción, qué significa cada estado, cómo elegir la vía de corrección y qué hacer ante los códigos de la AEAT más habituales. Cómo construir la factura está en references/emision.md; cómo funciona el remitente, en references/envio.md.

## Trampas

1. **Captura las excepciones fuera del bloque atómico**, para que la factura se deshaga con ellas, y **`ValidationError` antes que `ValueError`**: hereda de él. Un `ValueError` simple o un `TypeError` indican un fallo de tu código (indicadores del ciclo de vida, importes que no son `Decimal` o con más de dos decimales).
2. **Nunca corrijas editando ni borrando registros.** `Installation`, `Record`, `Submission` y `SubmissionLine` lanzan `ImmutableRecord`. Se corrige con un registro nuevo: `register`, `amend` o `cancel`.
3. **La vía de corrección depende del error, no del estado.** Rechazado o aceptado, un error que el reglamento de facturación obliga a rectificar se corrige con una factura rectificativa. Ver «Cómo corregir». Si no sabes qué vía aplica, pregunta al usuario: es una decisión fiscal, no técnica.
4. **`accepted_with_errors` no siempre exige actuar.** Decide con `record.needs_amendment`, que es `False` para 2004 y 2009.
5. **Un rechazo local del remitente no llega a `Submission.error_code`.** Está en `Submission.response` con la forma `Tipo: mensaje`, por ejemplo `ValidationError: [4120] ...` o `LookupError: ...`.
6. **Decide con el último registro de la factura.** Tras una subsanación aceptada, el rechazo anterior ya está resuelto.

## Excepciones de la librería

| Excepción | Cuándo | Qué hacer |
|---|---|---|
| `ValidationError` (`django_verifactu.aeat.violations`) | `register`, `amend` o `cancel` con datos que incumplen una regla de la AEAT, incluidos los límites del esquema y los valores en blanco (1100), o con un `SOFTWARE` inválido (`manage.py check` lo avisa como `E003`). No escribe nada | Corrige los datos. `error.violations` es una lista de `Violation(code, message)` con el código de la AEAT |
| `AlreadyRegistered` | `register` de una factura (emisor, número, fecha) que ya tiene un registro no rechazado (pendiente, aceptado, aceptado con errores o anulado), o a la que la AEAT respondió 3000 | No la registres otra vez (por ejemplo, un doble envío del formulario). Para cambiar su registro, ver «Cómo corregir» |
| `AlreadyCancelled` | `cancel` de una factura ya anulada, aunque la anulación siga pendiente | Nada |
| `LifecycleError` | La factura pertenece a otro objeto, o el objeto ya tiene registros de otra factura. Los rechazados no cuentan | Usa el objeto original. Una rectificativa es un objeto nuevo |
| `NotRegistered` | `qr_url(obj)` o `{% verifactu_qr obj %}` sin registro de alta no rechazado en el entorno actual | Registra antes de imprimir; un registro `pending` basta |
| `ValueError` | `Invoice` con `amendment` o `previous_rejection`; `Cancellation` con `without_previous_record` o `previous_rejection`; `new_installation` con un NIF inválido o sin cadena que reiniciar | Quita esos campos: la librería los decide |
| `TypeError`, `ValueError` | Importes que no son `Decimal` o tienen más de dos decimales; fechas `datetime` | Ver references/emision.md |
| `TransactionManagementError` (`django.db.transaction`) | `register`, `amend` o `cancel` fuera de `transaction.atomic()` | Llámalos en la transacción que guarda la factura |
| `RuntimeError` | `send_pending()` dentro de una transacción, incluido `ATOMIC_REQUESTS`, cuando hay algo que remitir | Llámalo fuera de transacciones |
| `ImmutableRecord` (`django_verifactu.models`) | `save`, `delete`, `update`, `create` o `bulk_create` sobre los modelos de la librería, también desde managers relacionados | No los escribas |
| `ProtectedError` (`django.db.models`) | Borrar un objeto con registros, directamente, en cascada o borrando su `ContentType` | Conserva el objeto |

Importa `AlreadyRegistered`, `AlreadyCancelled`, `LifecycleError` y `NotRegistered` desde `django_verifactu.issuing`. Las otras tres heredan de `LifecycleError`: captúralas antes que ella.

`ImproperlyConfigured` (`django.core.exceptions`) al emitir:

- El objeto no está guardado, o su modelo no tiene `VerifactuRecords` (references/emision.md).
- El objeto está en otra base de datos que la que el router da para `Record`.
- `SOFTWARE["system_id"]` cambió: ejecuta `python manage.py verifactu_new_installation NIF`.
- El sistema cuenta varios obligados tributarios (`IndicadorMultiplesOT` = S) y `SOFTWARE["multiple_taxpayers_possible"]` es `False`. Pon `True` si el sistema admite varios, o, en un SaaS, pon en `VERIFACTU["MULTIPLE_TAXPAYERS"]` la ruta con puntos de una función `(tax_id) -> bool`.

`django_verifactu.querying.query()` devuelve un iterador: al recorrerlo contacta con la AEAT y lanza `LookupError` (NIF sin entrada en `TAXPAYERS`), `OSError` (certificado ilegible), `ValueError` (contraseña errónea), `ValidationError` (filtros inválidos) y, desde `django_verifactu.aeat.soap`, `AeatFault` (con `error_code`), `NotDelivered`, `OutcomeUnknown` o `Refused`. `verify(aeat=True)` las convierte en una línea de su lista de problemas.

Patrón en una vista (`issue_sale` es el servicio de references/emision.md):

```python
from django.contrib import messages
from django_verifactu.aeat.violations import ValidationError
from django_verifactu.issuing import AlreadyRegistered

from .services import issue_sale


def create_sale(request, sale_fields: dict, line_fields: list[dict]):
    try:
        return issue_sale(sale_fields, line_fields)
    except ValidationError as error:
        # message está en inglés: a un usuario final, muéstrale tu propio texto según code.
        for violation in error.violations:
            messages.error(request, f"VERI*FACTU {violation.code}: {violation.message}")
    except AlreadyRegistered:
        messages.info(request, "La factura ya estaba registrada.")
    return None
```

## Estados de un registro

`Record.status` pasa una sola vez de `pending` a `accepted`, `accepted_with_errors` o `rejected`, con `error_code` y `error_description` de la AEAT. `record.needs_amendment` es `True` solo en `accepted_with_errors` con un código distinto de 2004 y 2009. Documento «Validaciones» de la AEAT para VERI*FACTU (versión 1.2.2), apartado 4.3.1:

> Los registros de facturación con errores admisibles serán “aceptados” y registrados por los sistemas de la AEAT, pero deberán ser subsanados para poder llevar a cabo el tratamiento y validación de los mismos.

El mismo apartado exceptúa la falta de `ClaveRegimen` con IPSI (2009) y el error de `FechaHoraHusoGenRegistro` (2004): «Se excepciona este error de la necesidad de ser subsanado». Estado de una factura, con su último registro del entorno actual:

```python
from django.conf import settings
from django_verifactu.models import Record


def last_record(obj) -> Record | None:
    records = obj.verifactu_records.filter(installation__production=settings.VERIFACTU["PRODUCTION"])
    return records.order_by("installation__generation", "position").last()


def needs_attention(obj) -> bool:
    record = last_record(obj)
    return record is not None and (record.status == Record.Status.REJECTED or record.needs_amendment)
```

Para reaccionar en cuanto llega la respuesta, conecta un receptor a `record_answered` (references/envio.md).

## Estados de un envío

`Submission.outcome` (detalle en references/envio.md). Salvo en `answered`, los registros siguen `pending`, el remitente reintenta solo y los avisos de registros sin remitir se muestran.

- `answered`: la AEAT respondió, aunque rechazara todos los registros. Revisa cada `Record`.
- `fault` con `error_code`: Fault SOAP de la AEAT; ver la lista de códigos. Si la causa está en tu configuración, se repite en cada reintento hasta que la corrijas.
- `fault` sin `error_code`: lee `response`. `the AEAT refused the certificate (HTTP 302 .../erro4011.html)` (ver erro4011), `LookupError` (el NIF no está en `TAXPAYERS`), `OSError` (certificado ilegible), `ValueError: Invalid password or PKCS12 data` (contraseña errónea) o `ValidationError: [código] ...` (cabecera: nombre, representante o `verifactu_end_date` del obligado tributario). `manage.py check` avisa como `django_verifactu.W001` de las entradas de `TAXPAYERS` inutilizables, con el certificado caducado o con una cabecera inválida.
- `not_delivered` (sin conexión, DNS o HTTP 429) y `unknown` (respuesta perdida o ilegible): nada; el reenvío es seguro y declara la incidencia.

## Cómo corregir

Preguntas frecuentes para desarrolladores de la AEAT (4-12-2025), apartado 17, después de expedir la factura:

- «Si los errores detectados tras la emisión están previstos en el reglamento de obligaciones de facturación (ROF), aprobado por el Real Decreto 1619/2012, deberá efectuarse su rectificación [...] lo que implica expedir nueva/s factura/s rectificativas de la factura original errónea». Crea otro objeto y llama a `register` con un `Invoice` de tipo R1 a R5 (references/emision.md).
- «Si los errores detectados tras la emisión NO están contemplados en el ROF, pero afectan a campos del registro de facturación (RF) generado al emitir la factura (que, digamos, “no se ven” en la factura impresa, es decir, son campos “internos”, como ciertas codificaciones tributarias), [...] se debe generar un RF de alta de subsanación». Llama a `amend(obj, invoice)` con la factura corregida completa.
- «Si se considera que "toda la factura" en sí misma está mal o no debería haberse emitido, siempre que para solucionarlo no deba emplearse algún procedimiento (de rectificativa u otro) previsto en el ROF, se podrá "anular"». Llama a `cancel(obj, Cancellation(issuer_tax_id, invoice_number, issue_date))`.

El documento «Validaciones», en 4.3.1: «Solo podrá llevarse a cabo una subsanación cuando no se trate de una causa que exija la emisión de una factura rectificativa (u otro mecanismo contemplado en el Reglamento de Facturación).»

Cómo aplica la librería cada vía (comprobado con la AEAT):

- Tras un alta rechazada con un código distinto de 3000, la AEAT no tiene la factura. `register(obj, corregida)` y `amend(obj, corregida)` envían `Subsanacion=S` y `RechazoPrevio=X`, la «subsanación, sin registro previo en la AEAT» del mismo apartado 17.
- `amend` sobre una factura anulada la reactiva: el diseño de registro lo describe como «Reactiva (vuelve a dejar de alta y en vigor) el registro de facturación anulado existente».
- Si `amend` cambia el importe total, la AEAT solo casa el QR con el importe nuevo: los QR ya impresos dejan de cotejarse y `qr_url(obj)` da el nuevo.
- Tras un `amend` o `cancel` rechazado, repite la misma llamada con los datos corregidos; la librería añade `RechazoPrevio` cuando corresponde.

## Códigos de la AEAT

Texto oficial entre comillas (errores.properties de la AEAT), y comportamiento comprobado en su entorno de pruebas.

### Rechazos locales: `ValidationError` antes de escribir nada

- **1100** «Valor o tipo incorrecto del campo.» Un valor en blanco o más largo que el esquema (descripción de más de 500 caracteres, nombres de más de 120, `ForeignId.number` de más de 20). Corrige el campo. En el remitente, el mismo código señala el nombre del obligado tributario o del representante en `TAXPAYERS`.
- **1104** «El valor del campo NumSerieFactura es incorrecto.» Número vacío, de más de 60 caracteres o con espacios al principio o al final.
- **1123** «El formato del NIF es incorrecto.» `issuer_tax_id` de un `Invoice` o `Cancellation`. Usa el NIF en mayúsculas y con su letra de control.
- **1130** «El campo NumSerieFactura contiene caracteres no permitidos.» Caracteres fuera del ASCII imprimible (`ñ`, `º`, tildes). Cambia el formato de la serie.
- **1287** «El valor del campo %s contiene carácteres no validos (<, >, ", ', =).» Quita esos caracteres del número.
- **1239** «Error en el bloque Destinatario.» NIF con letra de control errónea o en minúsculas, NIF-IVA con estructura incorrecta, IdType 07 con NIF de empresa. Corrige el destinatario.
- Los demás códigos locales los explica `violation.message`, y sus reglas están en references/emision.md.

### Respuesta por registro: `record.error_code`

- **1239** `rejected`. Comprobado: un NIF-IVA bien formado que no está en VIES. Confirma el dato con el cliente y corrige según «Cómo corregir».
- **1110** `rejected`, «El NIF no está identificado en el censo de la AEAT.» Comprobado con el NIF del productor en `SOFTWARE["producer"]`: afecta a todos los registros. Corrige `SOFTWARE` y vuelve a llamar a `register(obj, invoice)` para cada factura rechazada.
- **2001** `accepted_with_errors`, «El NIF del bloque Destinatarios no está identificado en el censo de la AEAT.» Comprobado con IdType 07 y un DNI no censado. `needs_amendment` es `True`. Confirma el NIF con el cliente y corrige según «Cómo corregir»; una subsanación con un destinatario censado se aceptó sin error.
- **2004** `accepted_with_errors`, fecha y hora de generación fuera de margen. Comprobado: más de 240 segundos de diferencia con el reloj de la AEAT, hacia atrás o hacia delante; con `Incidencia=S` no aparece. `needs_amendment` es `False`: no toques el registro. Sincroniza el reloj del servidor (NTP) y mantén el remitente en marcha.
- **3000** «Registro de facturación duplicado.» Tras reenviar un envío cuya respuesta se perdió, el remitente adopta el estado guardado en la AEAT: no hagas nada. Si el registro queda `rejected`, la AEAT tiene otro registro con ese emisor, número y fecha (otro sistema, una copia de seguridad restaurada o un número reutilizado; apartado 6 de las preguntas frecuentes). Averigua cuál: `python manage.py verifactu_verify --aeat` (contacta con la AEAT) informa «the AEAT holds #N, rejected here» cuando la AEAT tiene este mismo registro, pero no informa nada de esa factura cuando su registro es de otro sistema. Si es esta misma factura, repite la operación con `amend(obj, invoice)` o `cancel(obj, cancellation)`: la librería ajusta los indicadores y la AEAT la acepta. Si es otra factura, no la subsanes ni la anules, porque una subsanación «sustituye completamente al registro de facturación» que tiene la AEAT (diseño de registro); consulta al usuario. La librería permite registrar el mismo objeto con otro número.
- **1108** «El NIF del IDEmisorFactura debe ser el mismo que el NIF del ObligadoEmision.» Comprobado: la AEAT lo responde por registro, en altas y anulaciones. No ocurre: el remitente agrupa los registros por obligado tributario, que es su emisor.
- **3002** «No existe el registro de facturación.» Una subsanación o anulación de una factura que la AEAT no tiene, por ejemplo porque su alta se rechazó en el mismo envío. Repite la misma llamada: la librería la envía como operación sin registro previo.

### Envío rechazado entero: Fault (`Submission.error_code`) o `response`

- **4102** «El XML no cumple el esquema. Falta informar campo obligatorio.» La librería comprueba antes esas estructuras, así que no debería llegar. Si llega, conserva `Submission.response` y reporta el fallo de la librería.
- **4112** «El titular del certificado debe ser Obligado Emisión, Colaborador Social, Apoderado o Sucesor.» Comprobado en consultas con el NIF de otro obligado tributario. Configura en `TAXPAYERS` el certificado del propio obligado tributario, o el de quien actúe por él declarando `representative` (con el certificado de un tercero no se ha podido comprobar).
- **4114** «El XML no cumple con el esquema: se ha superado el límite máximo permitido de facturas a registrar.» Más de 1000 registros por envío; el remitente nunca envía más.
- **4116** NIF del obligado tributario en la cabecera con formato incorrecto. No ocurre: el remitente usa el NIF del emisor, validado al emitir (1123).
- **4120** «el valor del campo FechaFinVeriFactu es incorrecto, debe ser 31-12-20XX, donde XX corresponde con el año actual o el anterior.» Comprobado en 2026: la AEAT aceptó también el 30-06 del año en curso y rechazó el año siguiente. La librería exige el año en curso o el anterior y, desde 2027, el 31 de diciembre. Corrige o quita `verifactu_end_date` en `TAXPAYERS`.
- **4123** «el valor del campo NIF del bloque Representante no está identificado en el censo de la AEAT.» Comprobado también con una letra de control errónea. Corrige el NIF de `representative` en `TAXPAYERS`.
- **erro4011**: no es un Fault. Comprobado: con un certificado desconocido (autofirmado) o caducado, la AEAT redirige (HTTP 302) a `https://sede.agenciatributaria.gob.es/Sede/errores/erro4011.html` sin procesar nada. El envío queda `fault` solo para ese obligado tributario. Instala un certificado válido en `TAXPAYERS`; los pendientes se reenvían solos, declarando la incidencia.
