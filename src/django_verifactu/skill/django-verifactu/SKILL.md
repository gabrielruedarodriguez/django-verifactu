---
name: django-verifactu
description: >-
  Integra y mantiene la facturación VERI*FACTU de la AEAT (España) en proyectos Django con la
  librería django-verifactu: configuración, emisión de registros de alta, facturas
  rectificativas, subsanaciones, anulaciones, remisión a la AEAT, código QR tributario, avisos
  obligatorios, verificación de la cadena y requisitos legales (RD 1007/2023, Orden
  HAC/1177/2024). Úsala siempre que el trabajo toque facturas o django_verifactu, VERI*FACTU, la
  AEAT, registros de facturación, huellas, el QR de las facturas, certificados de la AEAT o la
  declaración responsable. Use it for any VERI*FACTU or AEAT invoicing task in a Django project.
license: Apache-2.0
metadata:
  library-version: "0.1.0"
---

# django-verifactu

django-verifactu genera, encadena y remite a la AEAT los registros de facturación VERI*FACTU de las facturas que el proyecto guarda en sus propios modelos, imprime su código QR, muestra los avisos que exige la Orden HAC/1177/2024 y verifica que la base de datos y la AEAT coinciden. El sistema informático de facturación es el proyecto que integra la librería: su productor responde de que cumpla la normativa y firma la declaración responsable.

Esta skill describe django-verifactu 0.1.0. Si el proyecto tiene otra versión instalada, pide al usuario que ejecute `python manage.py verifactu_skill` para instalar la skill de su versión.

Antes de escribir código de un área, lee su referencia (tabla al final). No completes de memoria lo que no esté aquí ni en las referencias.

## Reglas que no puedes romper

1. **Registra al expedir, en la misma transacción.** Llama a `register(obj, invoice)` dentro del `transaction.atomic()` que guarda la factura, después de guardar el objeto, y deja que sus excepciones salgan del bloque para que la factura tampoco se guarde. Fuera de una transacción lanza `TransactionManagementError`. Ver references/emision.md.
2. **Nunca reutilices un número de factura**, ni registres borradores, proformas o pruebas con `VERIFACTU["PRODUCTION"] = True`. La AEAT identifica cada factura por emisor, número y fecha de expedición.
3. **Un objeto, una factura.** El modelo lleva `verifactu_records = VerifactuRecords()`. Una factura rectificativa es otro objeto con su propio `register`. No cambies el número ni la fecha de un objeto ya registrado.
4. **Tipos exactos.** Importes y tipos en `Decimal` con dos decimales como máximo, fechas en `date`, NIF en mayúsculas sin espacios ni guiones. Los totales no se indican: la librería los calcula a partir de las líneas.
5. **Nunca pases `amendment`, `previous_rejection` ni `without_previous_record`.** La librería los decide a partir de los registros que ya tiene de esa factura, y lanza `ValueError` si los indicas.
6. **Corrige según el tipo de error, no según la respuesta de la AEAT** (FAQ para desarrolladores de la AEAT, apartado 17). Un error previsto en el reglamento de facturación (ROF), como un importe, un tipo o un destinatario, se corrige con una factura rectificativa nueva y `register`. Otros datos del registro que no se ven en la factura impresa se corrigen con `amend` y la factura completa ya corregida. `cancel` es solo para una factura que nunca debió expedirse. Si no sabes qué tipo de error es, pregunta al usuario: es una decisión jurídica. Ver references/correcciones.md.
7. **Nunca escribas en `Installation`, `Record`, `Submission` ni `SubmissionLine`**, ni intentes borrar un objeto con registros: la librería lo impide (`ImmutableRecord`, `ProtectedError`). Lee sus campos para mostrar el estado.
8. **La remisión la hace un proceso aparte.** Arranca `python manage.py verifactu_send --loop` como servicio, o una pasada por minuto desde un planificador; nunca una por hora. Nunca llames a `send_pending()` desde una petición web ni dentro de `transaction.atomic()` (tampoco con `ATOMIC_REQUESTS`). Ver references/envio.md.
9. **Toda factura lleva su QR.** Imprímelo con `{% load verifactu %}{% verifactu_qr factura %}` o, para PDF, con `django_verifactu.qr.qr_url(factura)`. Nunca construyas la URL a mano. `NotRegistered` significa que la factura no tiene registro de alta: no lo captures para imprimir sin QR. Ver references/qr-y-avisos.md.
10. **Los usuarios deben ver los avisos.** Pon `{% verifactu_notices <NIF de la empresa del usuario> %}` donde emiten facturas. Sin argumento muestra los avisos de todos los obligados tributarios: úsalo solo en pantallas de operadores. En Python, nunca llames a `notices(taxpayer_tax_id=None)` para un usuario concreto.
11. **Credenciales fuera del repositorio.** El certificado y su contraseña vienen de variables de entorno o de un almacén de secretos. No los imprimas en logs ni en respuestas. Ver references/configuracion.md.
12. **`PRODUCTION` lo decide el usuario.** Con `False` todo se remite al entorno de pruebas y el QR no valida facturas reales. Con `True` se remite de verdad y, según references/legal.md, se opta por VERI*FACTU al menos hasta el 31 de diciembre de ese año. No lo cambies sin que el usuario lo pida expresamente.
13. **`VERIFACTU["SOFTWARE"]` identifica el sistema del integrador, no django-verifactu.** Su `producer` es quien lo desarrolla, no quien factura: nunca saques de él el emisor de una factura, que es el obligado tributario de `TAXPAYERS`. Su productor firma la declaración responsable, que debe citar django-verifactu y su versión exacta como componente. Fija esa versión en las dependencias.
14. **No inventes códigos, reglas, límites ni fechas de la AEAT.** Si no están en las referencias, dilo y pide al usuario que lo consulte. No afirmes que un sistema «cumple»: explica qué cubre la librería y qué falta según references/legal.md.
15. **Comprueba tu trabajo.** Tras cada cambio: `python manage.py check` sin errores `django_verifactu.*` y los tests del proyecto en verde. Ver references/pruebas.md.

## Flujo de integración

Sigue los pasos en orden. Cada uno termina con su comprobación.

1. **Instalar.** Añade `django-verifactu==0.1.0` a las dependencias, `"django_verifactu"` a `INSTALLED_APPS` junto a `"django.contrib.contenttypes"`, y ejecuta `python manage.py migrate`. Necesita `USE_TZ = True`.
2. **Configurar.** Escribe `VERIFACTU` en settings con `PRODUCTION = False`, `SOFTWARE` y `TAXPAYERS` (references/configuracion.md). Comprueba: `python manage.py check`.
3. **Vincular el modelo.** Añade `VerifactuRecords()` al modelo de facturas; no necesita migración (references/emision.md).
4. **Traducir la factura.** Escribe una sola función que convierta una factura del proyecto en `django_verifactu.aeat.domain.Invoice`, y úsala tanto para `register` como para `amend` (references/emision.md).
5. **Registrar al expedir.** Llama a `register` en la transacción que expide la factura y muestra al usuario los errores de validación (references/errores.md).
6. **Corregir.** Ofrece rectificativas, subsanaciones y anulaciones según el criterio de la AEAT (references/correcciones.md).
7. **Imprimir el QR** en la factura HTML o PDF (references/qr-y-avisos.md).
8. **Mostrar los avisos** en la interfaz de los usuarios y conectar `alarm_raised` si hace falta avisar a alguien más (references/qr-y-avisos.md).
9. **Remitir.** Arranca el remitente como servicio y conecta las señales que necesites (references/envio.md).
10. **Probar.** Añade tests unitarios, tests con una AEAT falsa y, con un certificado real, contra el entorno de pruebas de la AEAT (references/pruebas.md).
11. **Verificar periódicamente.** Programa `python manage.py verifactu_verify` y `python manage.py verifactu_verify --aeat` (references/verificacion.md).
12. **Antes de producción,** repasa con el usuario la lista de references/legal.md: declaración responsable, identidad del software, certificados, QR, avisos, remitente y verificación.

## Cuando algo falla

- **Una llamada de la librería lanza una excepción:** lee references/errores.md.
- **Un registro queda `rejected` o `accepted_with_errors`,** o `record.needs_amendment` es `True`: lee references/errores.md y después references/correcciones.md.
- **Un envío termina en `fault`, o hay avisos de registros sin remitir:** lee references/envio.md y references/errores.md.
- **`verifactu_verify` informa de problemas,** o se ha restaurado una copia de seguridad de la base de datos: lee references/verificacion.md.
- **El usuario pregunta si algo es obligatorio, desde cuándo o quién responde:** lee references/legal.md y cita sus textos; no respondas de memoria.

## Referencias

| Archivo | Léelo cuando |
|---|---|
| references/configuracion.md | instales la librería, escribas `VERIFACTU`, conectes certificados, elijas la base de datos o `manage.py check` muestre `django_verifactu.*` |
| references/emision.md | conectes el modelo de facturas, construyas un `Invoice` (campos, códigos, tipos de factura, importes) o llames a `register` |
| references/correcciones.md | haya que corregir o anular una factura ya expedida, o antes de llamar a `amend` o `cancel` |
| references/envio.md | pongas en marcha o supervises la remisión, interpretes un `Submission` o conectes señales |
| references/qr-y-avisos.md | imprimas facturas con su QR o muestres los avisos de registros sin remitir y de la cadena |
| references/verificacion.md | programes o interpretes `verifactu_verify`, consultes a la AEAT, restaures una copia de seguridad o cambie `system_id` |
| references/pruebas.md | escribas tests de la integración |
| references/errores.md | aparezca una excepción, un estado de error o un código de la AEAT |
| references/legal.md | prepares el paso a producción o la declaración responsable, o surja una duda legal |
