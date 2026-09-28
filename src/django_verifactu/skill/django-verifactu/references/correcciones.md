# Corregir facturas: rectificativa, subsanación o anulación

Lee esto cuando una factura ya expedida tiene un error, cuando la AEAT rechaza un registro o lo acepta con errores, o antes de llamar a `amend` o `cancel`. Recoge el criterio de la AEAT (preguntas frecuentes para desarrolladores, «Aclaraciones a dudas de los desarrolladores» v1.3 de 4-12-2025, apartado 17), cómo decide la librería los indicadores `Subsanacion`, `RechazoPrevio` y `SinRegistroPrevio`, qué hacer con cada respuesta, las excepciones y el efecto de cada corrección en el código QR.

## Trampas

- **El camino lo decide el tipo de error, y clasificarlo es una cuestión jurídica.** Si no sabes si un error está previsto en el Reglamento por el que se regulan las obligaciones de facturación (ROF, RD 1619/2012), pregunta al usuario. No lo decidas tú.
- **El camino no depende de si el registro fue aceptado o rechazado.** Un error previsto en el ROF se corrige con una factura rectificativa aunque la AEAT haya rechazado el registro original.
- **Una rectificativa es una factura nueva**, con su propio objeto y su propio número, y se remite con `register`. Nunca uses `amend` sobre la factura original para rectificarla.
- **No anules facturas de operaciones reales** (ver el caso d).
- **`amend` recibe la factura corregida completa**, con la misma clave (`issuer_tax_id`, `invoice_number`, `issue_date`). Constrúyela desde tus datos ya corregidos, con la misma función que usaste para `register`. No es un parche de campos.
- **No pases nunca `amendment`, `previous_rejection` ni `without_previous_record`.** La librería los decide a partir de los registros que ya tiene de esa factura. Si los pasas, lanza `ValueError`.
- **Pasa el objeto de la propia factura y llama dentro de `transaction.atomic()`**, la misma transacción que guarda la corrección en tu modelo.
- **Un rechazo 3000 o 3002 no se arregla cambiando datos**: llama a `amend` o repite `cancel` (ver «Después de la respuesta de la AEAT»).

## El criterio de la AEAT

Citas literales de las preguntas frecuentes para desarrolladores, apartado 17 («Forma de proceder ante errores cometidos al facturar»):

1. Antes de expedir: «Si los errores se detectan "mientras se está confeccionando la factura", es decir, cuando se está editando pero aún no se ha emitido, se corrigen sin más antes de emitirla.»
2. Después de expedir:
   - a) «Si los errores detectados tras la emisión están previstos en el reglamento de obligaciones de facturación (ROF), aprobado por el Real Decreto 1619/2012, deberá efectuarse su rectificación de acuerdo con el procedimiento que indique el ROF según el tipo de error de que se trate, lo que implica expedir nueva/s factura/s rectificativas de la factura original errónea [...]»
   - b) «Si los errores detectados tras la emisión NO están contemplados en el ROF, pero afectan a campos del registro de facturación (RF) generado al emitir la factura (que, digamos, “no se ven” en la factura impresa, es decir, son campos “internos”, como ciertas codificaciones tributarias), se debe corregir la factura original (esos datos “internos” de la misma) y se debe generar un RF de alta de subsanación de esa factura donde conste ya la nueva información que proceda. Estos casos deberían ser MUY POCO FRECUENTES.»
   - c) «Si los errores detectados tras la emisión NO están contemplados en el ROF ni afectan a campos del registro de facturación (RF) generado al emitir la factura, se corrige la factura original sin que sea preciso generar un nuevo RF de ningún tipo.»
   - d) «Si se considera que "toda la factura" en sí misma está mal o no debería haberse emitido, siempre que para solucionarlo no deba emplearse algún procedimiento (de rectificativa u otro) previsto en el ROF, se podrá "anular" generando para ello un RF de anulación. Estos casos deberían ser MUY POCO FRECUENTES.» Y añade: «Con carácter general, todas las facturas emitidas, en la medida en que respondan a operaciones realmente efectuadas (como es el caso habitual) no pueden anularse.»

En la librería:

| Caso | Qué haces | Llamada |
|------|-----------|---------|
| 1 | Corriges antes de llamar a `register` | ninguna |
| 2.a | Expides una rectificativa: objeto y número nuevos | `register(rectificativa, Invoice(invoice_type=InvoiceType.R1, ...))` |
| 2.b | Subsanas el registro con la factura completa corregida | `amend(obj, corregida)` |
| 2.c | Corriges solo tu modelo | ninguna |
| 2.d | Anulas | `cancel(obj, Cancellation(...))` |

Más aclaraciones del mismo apartado:

- Caso 2.a con el registro original rechazado o aceptado: «no habría que hacer nada más en cuanto a la factura errónea original ni a su/s RF. No obstante, dichas situaciones de error se dan por solucionadas en este caso cuando se reciba/n correctamente RF de la/s nueva/s factura/s rectificativa/s de la factura errónea original (que indicará/n a qué factura está/n rectificando).» Por eso, pasa `corrected_invoices` con las facturas que rectificas. Excepción, en los rappels (mismo documento, apartado 19): «No es necesario identificar en la factura rectificativa las facturas rectificadas, basta con indicar el periodo al que refieren.»
- Caso 2.b con el registro original rechazado: hay que «corregir la factura original y generar un RF de alta de subsanación, sin registro previo en la AEAT (ya que el RF “original” fue rechazado y no existe en la AEAT)», con `Subsanacion` = "S" y `RechazoPrevio` = "X". La librería los pone sola.
- Casos 2.b y 2.d: «en principio, tanto un RF de alta de subsanación como un RF de anulación se podrían generar y conservar o remitir a la AEAT desde un SIF distinto al que expidió la factura original».
- Plazo de una subsanación o una anulación: «esto deberá hacerse en cuanto sea posible tras realizar las acciones que procedan -según el caso- para solucionar el error, no existiendo, en principio, un plazo máximo fijado para ello.»

## Rectificativa (caso 2.a)

```python
from datetime import date
from decimal import Decimal

from django.db import transaction
from django_verifactu.aeat.codes import CorrectionType, InvoiceType
from django_verifactu.aeat.domain import Invoice, InvoiceId, Party, TaxLine
from django_verifactu.issuing import register

from myapp.models import Sale  # tu modelo, con verifactu_records = VerifactuRecords()

# Rectifica A-2026/001 por diferencias: su base imponible baja 20 €.
with transaction.atomic():
    credit = Sale.objects.create(number="R-2026/001")
    register(
        credit,
        Invoice(
            issuer_tax_id="B12345674",
            issuer_name="Acme SL",
            invoice_number="R-2026/001",
            issue_date=date(2026, 9, 28),
            description="Rectificación de la factura A-2026/001",
            recipients=(Party("Cliente", tax_id="12345678Z"),),
            lines=(TaxLine(base=Decimal("-20.00"), rate=Decimal("21"), tax=Decimal("-4.20")),),
            invoice_type=InvoiceType.R1,  # según la causa: pregúntalo (lista L2)
            correction_type=CorrectionType.DIFFERENCES,
            corrected_invoices=(InvoiceId("B12345674", "A-2026/001", date(2026, 9, 28)),),
        ),
    )
```

- `invoice_type`, según la lista L2 del diseño de registros de la AEAT (DsRegistroVeriFactu): «R1 Factura Rectificativa (Error fundado en derecho y Art. 80 Uno Dos y Seis LIVA)», «R2 Factura Rectificativa (Art. 80.3)», «R3 Factura Rectificativa (Art. 80.4)», «R4 Factura Rectificativa (Resto)», «R5 Factura Rectificativa en facturas simplificadas». Una R5 no lleva destinatarios (1190).
- `correction_type` es obligatorio en una R (1114): `CorrectionType.DIFFERENCES` («I», por diferencias) o `CorrectionType.SUBSTITUTION` («S», por sustitución).
- Por sustitución exige `corrected_amounts=CorrectedAmounts(base=..., tax=...)` (1118), y por diferencias lo prohíbe (1119). El diseño de registros describe esos campos como «Base imponible de la factura» y «Cuota repercutida o soportada de la factura». La librería no admite la cuota de recargo rectificada (`CuotaRecargoRectificado`).
- `corrected_invoices` solo se admite en una R (1117). La AEAT no lo exige («no es obligatoria», Validaciones 3.1.3), pero la cita anterior del caso 2.a espera que la rectificativa indique qué factura rectifica.
- La factura original no se toca: sus registros, su objeto y su QR siguen igual.

## Subsanación (caso 2.b)

```python
from django.db import transaction
from django_verifactu.issuing import amend

from myapp.verifactu import invoice_for  # tu función: construye el Invoice completo desde el modelo

with transaction.atomic():
    sale.save()  # la corrección en tu modelo; sale es el objeto de la factura original
    record = amend(sale, invoice_for(sale))
```

La AEAT describe el alta de subsanación como la que «deja constancia de los nuevos datos que deben ser tenidos en cuenta» (descripción de los servicios web, Veri-Factu_Descripcion_SWeb v1.0.3, 9.1.2), y advierte: «Solo podrá llevarse a cabo una subsanación cuando no se trate de una causa que exija la emisión de una factura rectificativa (u otro mecanismo contemplado en el Reglamento de Facturación).» (Validaciones v1.2.2, 4.3.1).

## Anulación (caso 2.d)

```python
from datetime import date

from django.db import transaction
from django_verifactu.aeat.domain import Cancellation
from django_verifactu.issuing import cancel

with transaction.atomic():
    cancel(sale, Cancellation("B12345674", "A-2026/001", date(2026, 9, 28)))
```

El Reglamento aprobado por el RD 1007/2023 prevé la anulación «cuando se haya emitido erróneamente una factura y sea por lo tanto necesario anular su correspondiente registro de facturación de alta» (art. 11.1, https://www.boe.es/buscar/act.php?id=BOE-A-2023-24840#a1-3). Según la AEAT, que la factura no se haya entregado al cliente favorece que sea «susceptible de anularse y, después, si procede, expedir una nueva factura "original" (no rectificativa) correcta que se entregaría al cliente». Esa factura nueva es otro objeto con otro número, y va con `register`: la clave anulada no se puede volver a registrar (`AlreadyRegistered`), y el objeto anulado no admite otra factura (`LifecycleError`).

## Cómo decide la librería los indicadores

La librería reúne los registros de la misma clave (NIF del emisor, número y fecha de expedición), del mismo entorno (`PRODUCTION`) y de todas las instalaciones del obligado tributario, y los recorre en orden:

- un alta o una anulación `pending`, `accepted` o `accepted_with_errors` deja la factura registrada o anulada (un registro pendiente cuenta ya, se haya remitido o no);
- un rechazo 3000 significa que la AEAT ya tiene la factura;
- un rechazo 3002 significa que la AEAT no la tiene;
- cualquier otro rechazo no cambia nada, porque la AEAT no guardó ese registro.

| Estado de la factura | `register` | `amend` | `cancel` |
|----------------------|------------|---------|----------|
| Sin ningún registro | alta normal | `Subsanacion=S`, `RechazoPrevio=X` | `SinRegistroPrevio=S` |
| La AEAT no la tiene (solo rechazos distintos de 3000, o un 3002) | `Subsanacion=S`, `RechazoPrevio=X` | `Subsanacion=S`, `RechazoPrevio=X` | `SinRegistroPrevio=S` |
| Registrada, o la AEAT la tiene (3000) | `AlreadyRegistered` | `Subsanacion=S` | anulación normal |
| Anulada | `AlreadyRegistered` | `Subsanacion=S` (la reactiva) | `AlreadyCancelled` |

Además, `amend` añade `RechazoPrevio=S` cuando el último registro de la factura es una subsanación rechazada (salvo si la AEAT no tiene la factura: entonces va `X`), y `cancel` añade `RechazoPrevio=S` cuando el último registro es una anulación rechazada, con `SinRegistroPrevio=S` o sin él.

En la fila «La AEAT no la tiene», `register` y `amend` producen lo mismo (`S` + `X`). Tras un rechazo, usa `amend`: nunca lanza `AlreadyRegistered`.

Cada entorno tiene su propio ciclo de vida, y una factura emitida desde una instalación anterior se subsana o anula igual desde la nueva (references/verificacion.md).

## Después de la respuesta de la AEAT

| Respuesta en el `Record` | Qué significa | Qué haces |
|--------------------------|---------------|-----------|
| `accepted` | La AEAT lo guardó | Nada |
| `accepted_with_errors` y `needs_amendment` | Error admisible: «serán “aceptados” y registrados por los sistemas de la AEAT, pero deberán ser subsanados» (Validaciones, 4.3.1) | Caso 2.b: `amend`. Si el error está previsto en el ROF: rectificativa |
| `accepted_with_errors` 2004 o 2009 | Errores que 4.3.1 excepciona «de la necesidad de ser subsanado» | Nada (`needs_amendment` es `False`) |
| `rejected` 3000 | La AEAT ya tiene una factura con ese NIF, número y fecha | `amend` (o `cancel` otra vez) con los datos vigentes de la factura. Si el 3000 responde a un alta (`register`, o `amend` con `RechazoPrevio=X`), confirma antes con `query` que es esta factura y no otra con el mismo número: `amend` sustituiría sus datos en la AEAT. Si es otra, pregunta al usuario |
| `rejected` 3002 | La AEAT no tiene la factura | La misma llamada otra vez |
| `rejected`, otro código | Error en los datos; la AEAT no guardó el registro | Corrige y `amend` (o `cancel` otra vez); si es un error previsto en el ROF, rectificativa |

Si una remisión perdió su respuesta, el remitente la reenvía y acepta como propio el 3000 de un alta normal, o el de una anulación si la AEAT responde que la factura consta anulada. Una subsanación reenviada que recibe 3000 queda `rejected`: vuelve a llamar a `amend`.

Comprobado en el entorno de pruebas de la AEAT:

| Situación | Llamadas | Resultado |
|-----------|----------|-----------|
| Alta rechazada (1239) | `register` otra vez: `S` + `X` | aceptada |
| Alta aceptada con error 2001 | `amend`: `S` | aceptada |
| Subsanación rechazada (1239) | `amend`: `S` + `RechazoPrevio=S` | aceptada |
| Alta rechazada (1239) y anulación rechazada (3002) en el mismo envío | `cancel`: `SinRegistroPrevio=S` + `RechazoPrevio=S` | aceptada |
| Factura anulada | `amend`: `S` | aceptada, la reactiva |
| Factura remitida por otro SIF | `amend`: `S` + `X`, 3000; `amend`: `S` + `RechazoPrevio=S`; `cancel` | aceptadas las dos últimas |
| Factura remitida por otro SIF | `cancel`: `SinRegistroPrevio=S`, 3000; `cancel`: `RechazoPrevio=S` | aceptada |

Con una factura remitida por otro sistema, o que tu base de datos perdió, la librería no tiene historial: cuenta con un primer rechazo 3000 de `amend` o `cancel` y repite la misma llamada.

## Excepciones

Ninguna deja nada escrito en las tablas de la librería.

| Excepción | Cuándo |
|-----------|--------|
| `django_verifactu.aeat.violations.ValidationError` | Los datos incumplen una regla de la AEAT; `violations` lleva sus códigos. Es subclase de `ValueError`: captúrala antes |
| `ValueError` | Pasaste `amendment`, `previous_rejection` o `without_previous_record` |
| `AlreadyRegistered` | `register` sobre una factura registrada (pendiente o no), anulada o que la AEAT ya tiene. Para corregirla, `amend` (sobre una anulada, la reactiva) |
| `AlreadyCancelled` | `cancel` sobre una factura ya anulada |
| `LifecycleError` | La factura pertenece a otro objeto, o el objeto ya tiene registros de otra factura (una rectificativa necesita su propio objeto). Los registros rechazados no atan ninguna factura a un objeto |
| `TransactionManagementError` | Llamada fuera de una transacción |
| `ImproperlyConfigured` | Objeto sin guardar, modelo sin `VerifactuRecords`, base de datos distinta de la del objeto, `SOFTWARE["system_id"]` cambiado (references/verificacion.md), o `SOFTWARE["multiple_taxpayers_possible"]` es `False` y hay más de un obligado tributario |

`AlreadyRegistered`, `AlreadyCancelled` y `NotRegistered` son subclases de `LifecycleError`, y todas se importan de `django_verifactu.issuing`: captúralas antes que `LifecycleError`.

## Efecto en el código QR

- `qr_url(obj)` y `{% verifactu_qr obj %}` usan la última alta no rechazada del objeto en el entorno actual, aunque esté pendiente. Tras `amend`, el QR sale de la subsanación en el acto.
- Comprobado en la AEAT: si la subsanación cambia el importe total, solo valida el importe nuevo, y los QR impresos con el anterior dejan de encontrarse. Vuelve a imprimir o enviar la factura. Antes de subsanar un importe, recuerda el apartado 17: «En el caso de que exista alguna diferencia entre lo facturado y la realidad, por ejemplo, que por un defecto de cantidades o de calidades, o por otras razones, y se deba modificar su importe, procederá la emisión de una factura rectificativa».
- Si la subsanación se rechaza, el QR vuelve al alta anterior.
- Una factura anulada conserva su QR para reimpresiones, pero la AEAT ya no la da por encontrada.
- Una rectificativa tiene su propio QR, el de su objeto.
- Un objeto sin alta viva (solo rechazos o solo una anulación) lanza `NotRegistered`.
