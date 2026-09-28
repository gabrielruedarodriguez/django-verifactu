# Verificar las cadenas, consultar a la AEAT y reiniciar una cadena

Lee esto para programar comprobaciones periódicas, cuando `verifactu_verify` informa de problemas, cuando necesitas saber qué tiene la AEAT (`django_verifactu.querying.query`), después de restaurar una copia de seguridad de la base de datos o cuando cambia `VERIFACTU["SOFTWARE"]["system_id"]`. Explica qué comprueba `manage.py verifactu_verify` y qué no, qué hacer con cada mensaje, cada cuánto ejecutarlo, cuándo usar `manage.py verifactu_new_installation` y el procedimiento tras restaurar una copia.

## Trampas

- **Sin `--aeat` no se detecta una restauración de copia de seguridad**: la cadena restaurada es coherente consigo misma. Solo `--aeat` ve las facturas que la AEAT tiene y la base de datos no.
- **La comprobación local solo cubre la huella y unas pocas columnas** (ver abajo). No detecta cambios en la descripción, los destinatarios o el desglose del XML, ni en el estado (`status`) de un registro.
- **Tras restaurar una copia o cambiar `system_id`, reinicia la cadena de cada obligado tributario antes de emitir nada** con `verifactu_new_installation`.
- **No reinicies la cadena por actualizar la versión de tu software**: «un cambio en dicha versión (cuando se actualiza, por ejemplo) no significa que el SIF pase a ser otro SIF con Id. distinto» (preguntas frecuentes para desarrolladores, apartado 4).
- **No edites las tablas de django_verifactu para arreglar un problema.** El ORM lo impide (`ImmutableRecord`). Una edición por SQL altera la evidencia y el historial del que la librería deduce los indicadores de `amend` y `cancel`, y `verifactu_verify` solo detecta parte de esas ediciones.
- **`--aeat` consulta a la AEAT mes a mes desde la primera factura** de cada obligado tributario. Con muchos obligados tributarios, repártelo con `--taxpayer`.
- Todo trabaja solo con el entorno de `VERIFACTU["PRODUCTION"]`.

## verifactu_verify

```console
python manage.py verifactu_verify                        # todas las cadenas, en local
python manage.py verifactu_verify --taxpayer B12345674   # un obligado tributario
python manage.py verifactu_verify --aeat                 # además, compara con la AEAT (la consulta)
```

Escribe un problema por línea y termina con error (código de salida 1, «N problems found») si encuentra alguno; si no, escribe `no problems found`. En código, `django_verifactu.verifying.verify(taxpayer_tax_id=None, aeat=False)` devuelve la misma lista de textos; sus argumentos solo se pasan por nombre, por ejemplo `verify(taxpayer_tax_id="B12345674", aeat=True)`.

La Orden HAC/1177/2024 pide que el sistema pueda «comprobar si es correcta toda o una determinada parte de la cadena de registros de facturación [...] permitiendo realizar esta comprobación, bajo demanda, de forma rápida, fácil e intuitiva» (art. 6.e, https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a6), y añade que «podrá ofrecer el lanzamiento, periódico o bajo demanda, de un proceso de comprobación de toda o de parte de la cadena» (art. 7.h, https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a7).

### Qué comprueba en local

Recorre cada registro de todas las cadenas (todas las instalaciones) y comprueba que:

- las posiciones son consecutivas;
- no se generó más de un minuto antes que el registro anterior;
- su XML se puede leer;
- la huella recalculada desde el XML, la `Huella` del XML y la columna `fingerprint` coinciden;
- las columnas de operación, NIF, número, fecha de expedición y subsanación coinciden con el XML;
- su encadenamiento apunta al registro anterior, o es `PrimerRegistro` si es el primero.

La huella solo cubre, en un alta, `IDEmisorFactura`, `NumSerieFactura`, `FechaExpedicionFactura`, `TipoFactura`, `CuotaTotal`, `ImporteTotal`, la huella anterior y `FechaHoraHusoGenRegistro`; en una anulación, el emisor, el número y la fecha de la factura anulada, la huella anterior y `FechaHoraHusoGenRegistro`. Un cambio en cualquier otro campo del XML no se detecta.

Además, antes de generar cada registro la librería comprueba el último, como exige el art. 7.i de la Orden: «1.º El último registro de facturación generado está correctamente encadenado. 2.º La fecha y hora de generación del último registro de facturación generado no es superior en más de un minuto a la fecha y hora actuales que se utilizarán para fechar el registro de facturación a generar.» Si falla, emite igualmente, anota el problema como error en el log y envía `alarm_raised`. Los avisos (`notices`, `{% verifactu_notices %}`) revisan los 20 últimos registros de cada cadena; `verifactu_verify` revisa las cadenas completas.

### Qué compara con `--aeat`

- Para cada obligado tributario con cadena en la base de datos, consulta a la AEAT cada mes de expedición, desde el de la primera factura hasta el más tardío entre el de la última y el actual. Necesita sus credenciales de `TAXPAYERS`.
- La AEAT conserva, por factura, el último registro que aceptó (comprobado). Se espera que coincida, por su huella, con el último registro aceptado aquí o con uno pendiente posterior, que puede haber llegado ya.
- Vuelve a leer la base de datos tras la respuesta, y pregunta de nuevo por una factura antes de darla por ausente: emitir y remitir mientras se ejecuta no produce falsos problemas.
- Ignora las facturas de otros sistemas de las que no tienes registros.
- Si un mes no se puede consultar, lo informa y deja de comparar ese obligado tributario: los meses siguientes quedan sin comprobar.

### Mensajes y qué hacer

Los problemas locales empiezan por la instalación y el registro, y los de la AEAT por la factura:

```text
B12345674 production #1 #57 (Alta A-2026/001 28-09-2026): its XML or its fingerprint was altered
B12345674 A-2026/001 28-09-2026: the AEAT does not hold #57
```

`production #1` es el entorno y la generación de la instalación, y `#57` la posición del registro en su cadena.

| Problema local | Significa | Qué hacer |
|----------------|-----------|-----------|
| `the chain should continue with #N` | Falta el registro #N o hay registros fuera de su sitio | Alguien borró o movió filas fuera de la librería, o se restauró solo parte de la base de datos. Averigua la causa con el usuario |
| `it was generated more than a minute before the record before it` | El reloj retrocedió más de un minuto | Corrige la hora del servidor: el obligado tributario «deberá asegurarse de que la fecha y hora empleadas por dicho sistema informático para fechar los registros de facturación son exactas, con un margen máximo de error admitido de un minuto» (Orden HAC/1177/2024, art. 7.f, https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a7) |
| `its XML cannot be read` | El XML guardado está dañado | Averigua la causa. `query` muestra lo que la AEAT conserva de esa factura |
| `its XML or its fingerprint was altered` | Se modificó el XML o la huella | Averigua quién escribió en la tabla |
| `its columns do not match its XML` | Se modificaron las columnas del registro | Averigua la causa. La librería decide los indicadores de `amend` y `cancel` con esas columnas, así que no corrijas esa factura hasta aclararlo |
| `it does not follow the record before it` | Su encadenamiento no apunta al registro anterior | Suele acompañar a otro problema del registro anterior: empieza por ese |

La librería no repara estos problemas ni deja de emitir por ellos. Los avisos los muestran mientras afecten a los 20 últimos registros de una cadena. Informa al usuario y no toques filas. Solo en `alarm_raised` y en el log aparece además `it was generated more than a minute after now`: el último registro tiene una fecha posterior a la hora actual, así que el reloj está atrasado ahora o estuvo adelantado entonces.

| Problema con la AEAT | Significa | Qué hacer |
|----------------------|-----------|-----------|
| `the AEAT does not hold #N` | La AEAT no tiene ningún registro de esa factura, aunque aquí #N consta aceptado | Averigua cómo cambió su estado. Si #N es un alta y la AEAT debe tener la factura, subsánala con `amend`; si responde 3002, repite (references/correcciones.md) |
| `the AEAT holds it from this system, but the database does not` | La AEAT tiene una factura de una instalación de esta base de datos, y la base de datos no tiene ningún registro de ella | Típico tras restaurar una copia: sigue el procedimiento de abajo |
| `the AEAT holds #N, rejected here`, a veces con `instead of #M` | La AEAT tiene un registro que aquí consta rechazado | Pasa, por ejemplo, con registros pendientes reenviados tras restaurar una copia. Si ese registro era su única alta, la factura no tiene QR (`NotRegistered`). La única vía de la librería es subsanarla con `amend` con sus datos vigentes: la AEAT guardará la subsanación como último registro y la comparación cuadrará. Decídelo con el usuario |
| `the AEAT holds #N, accepted here instead of #M` (u otro estado) | La AEAT tiene un registro anterior de esta cadena, no el último aceptado aquí | El estado de #M no refleja lo ocurrido en la AEAT: averigua la causa |
| `the AEAT holds a record of this system the database does not have` | La AEAT tiene un registro de esta factura con un número de instalación de esta base de datos, pero la base de datos no lo tiene | Otra copia de esta base de datos (una restauración, un clon) generó registros, o se borraron filas. Tras una restauración, sigue el procedimiento de abajo; si es un clon que remite, detenlo |
| `the AEAT holds another system's record` | Otro sistema remitió después un registro de esta factura | La AEAT lo admite (references/correcciones.md). Confírmalo con el usuario; `query(..., show_software=True)` muestra qué sistema fue |
| `B12345674: the AEAT could not be queried for 09-2026: <Tipo>: <mensaje>` | No se pudo consultar ese mes | Corrige la causa (`LookupError`: faltan las credenciales en `TAXPAYERS`) y repite |

### Cada cuánto

La Orden no fija una frecuencia para la comprobación completa (art. 7.h). Por defecto (recomendación, no exigencia normativa):

- `verifactu_verify` una vez al día, desde cron o tu planificador, con una alerta si termina con error;
- `verifactu_verify --aeat` una vez al mes, al cerrar el mes, y siempre después de restaurar una copia, de un incidente con los envíos o de cualquier intervención manual en la base de datos.

La comprobación local lee el XML de todos los registros, en páginas de 1000. `--aeat` hace al menos una consulta por mes y obligado tributario, y la AEAT devuelve hasta 10 000 registros por página (comprobado).

## Consultar a la AEAT: query

`django_verifactu.querying.query` ejecuta la consulta de la AEAT con las credenciales de `TAXPAYERS`, en el entorno de `PRODUCTION`, y sigue todas las páginas. Contacta con la AEAT.

```python
from django_verifactu.querying import query

for stored in query("B12345674", year=2026, month=9, invoice_number="A-2026/001"):
    print(stored.invoice.invoice_number, stored.status, stored.fingerprint)
```

- Es un generador: la primera petición sale al recorrerlo, y ahí se lanzan sus errores.
- `year` y `month` son el mes de expedición: la AEAT archiva cada factura en ese mes, no en el de su remisión (comprobado).
- Filtros, con los nombres de `django_verifactu.aeat.domain.Query`: `invoice_number` y `external_reference` (coincidencia exacta), `issue_date` o el intervalo `issued_from`/`issued_to` (no ambos; `issued_from` debe ser anterior a `issued_to`), `counterparty`, `software`, `as_recipient`, `as_representative`, `show_issuer_name` y `show_software`.
- Devuelve `StoredRecord`: `invoice`, `status` (`StoredStatus.ACCEPTED` «Correcto», `ACCEPTED_WITH_ERRORS` «AceptadoConErrores» o `CANCELLED` «Anulado»), `error_code`, `fingerprint`, `total_amount`, `software` (con `show_software=True`; puede ser `None`), `needs_amendment` y más.
- Comprobado: una entrada por factura, con los datos y la huella de su último registro aceptado (una subsanación aparece con su importe nuevo, una anulación como `Anulado`); los registros rechazados nunca aparecen; cada registro es visible en cuanto llega la respuesta del envío.
- Con `as_recipient=True` busca las facturas recibidas por ese NIF y solo trae datos de la factura, sin huella ni encadenamiento; no admite `show_software` ni `as_representative`.
- Un filtro inválido lanza `django_verifactu.aeat.violations.ValidationError` sin contactar. Los errores de la AEAT llegan como `django_verifactu.aeat.soap.AeatFault`, con su código en `error_code`.

## Reiniciar una cadena: verifactu_new_installation

```console
python manage.py verifactu_new_installation B12345674
```

Escribe la instalación nueva y su número, por ejemplo `B12345674 production #2: installation number 5F0C...`. En código, `django_verifactu.issuing.new_installation("B12345674")` devuelve la `Installation`.

Úsalo en estos dos casos, no por rutina:

- **Después de restaurar una copia de seguridad** (procedimiento de abajo).
- **Cuando cambia `SOFTWARE["system_id"]`.** Hasta que lo hagas, `register`, `amend` y `cancel` de ese obligado tributario lanzan `ImproperlyConfigured("SOFTWARE system_id changed: start a new installation")`. Despliega el ajuste nuevo y ejecuta el comando para cada obligado tributario antes de volver a emitir.

No hace falta para empezar: el primer `register` crea la cadena, y el comando falla con un obligado tributario sin cadena en el entorno.

Efectos:

- Abre una generación nueva de la cadena del obligado tributario en este entorno, con un número de instalación nuevo; sus registros empiezan en #1 con `PrimerRegistro`.
- Los registros pendientes de la cadena anterior se remiten primero.
- Las facturas de instalaciones anteriores conservan su historial: se subsanan o anulan desde la nueva.
- `verifactu_verify` sigue comprobando todas las instalaciones.
- Comprobado en el entorno de pruebas de la AEAT: la instalación nueva con `PrimerRegistro` se acepta sin el error 2007, los pendientes de la anterior se siguen aceptando, una subsanación de una factura anterior desde la nueva se acepta y `verifactu_verify --aeat` queda limpio.

Sobre el número de instalación, la AEAT dice que «no puede repetirse nunca: por ejemplo, incluso si se formatea el ordenador donde estaba instalado un SIF y se reinstala el mismo software de nuevo en ese mismo ordenador, el nuevo SIF así constituido debe llevar otro nº de instalación diferente al anterior que tenía» (preguntas frecuentes para desarrolladores, apartado 4). Interpretación de la librería: una base de datos restaurada es un caso análogo.

Para reiniciar todos los obligados tributarios del entorno:

```python
from django.conf import settings
from django_verifactu.issuing import new_installation
from django_verifactu.models import Installation

production = settings.VERIFACTU["PRODUCTION"]
installations = Installation.objects.filter(production=production)
for tax_id in sorted(set(installations.values_list("taxpayer_tax_id", flat=True))):
    print(new_installation(tax_id))
```

## Restaurar una copia de seguridad

1. Mantén paradas la aplicación y `verifactu_send` hasta el paso 5. Antes del paso 3, un registro nuevo se encadenaría a un registro que ya no es el último de su instalación; antes del paso 4, podría repetir un número de factura.
2. Restaura la base de datos.
3. Reinicia la cadena de cada obligado tributario (el script anterior).
4. Ejecuta `python manage.py verifactu_verify --aeat`. Cada `the AEAT holds it from this system, but the database does not` es una factura expedida después de la copia, y sigue expedida. Recupérala en tu sistema por tus medios y adelanta tus series de numeración más allá de los números que tiene la AEAT: un alta con la misma clave (NIF, número y fecha) que una que tiene la AEAT se rechaza con 3000. Cada `the AEAT holds a record of this system the database does not have` es una factura de la copia que se subsanó o anuló después: recupera sus datos vigentes con `query` y por tus medios antes de volver a corregirla. Un obligado tributario cuya primera factura es posterior a la copia no tiene cadena en la base restaurada y `--aeat` no lo consulta: revísalo con `query`.
5. Arranca la aplicación y `verifactu_send`. Los registros pendientes de la copia se remiten primero, y los que ya habían llegado a la AEAT pueden volver rechazados con 3000.
6. Cuando no queden pendientes, repite `verifactu_verify --aeat` y resuelve cada línea con las tablas de arriba.
7. Una factura perdida no tiene registros en la base de datos, así que `qr_url` lanza `NotRegistered` para ella. Si más adelante la subsanas o la anulas, la librería no tiene su historial: el primer `amend` o `cancel` recibirá 3000 y basta con repetirlo (references/correcciones.md).
