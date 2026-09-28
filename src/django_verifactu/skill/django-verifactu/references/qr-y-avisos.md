# Código QR y avisos a los usuarios

Lee este archivo cuando imprimas facturas (HTML, PDF o factura electrónica estructurada), cuando tengas que mostrar a los usuarios los avisos de registros sin remitir o de problemas en la cadena, o cuando conectes `alarm_raised`. Cómo funciona la remisión que alimenta esos avisos está en references/envio.md; qué exige la normativa en conjunto, en references/legal.md.

## Trampas

1. **Pasa a `{% verifactu_qr %}` y a `qr_url()` el objeto de tu factura**, el modelo con `VerifactuRecords`, nunca un `Record`. No montes la URL tú: la librería la toma del registro de alta tal como se registró (NIF, número, fecha de expedición e `ImporteTotal`).
2. **Un objeto sin registro de alta válido en el entorno actual lanza `NotRegistered`**, también al renderizar la etiqueta. No lo captures para imprimir la factura sin QR: registra la factura en la misma transacción que la guarda.
3. **Con `VERIFACTU["PRODUCTION"] = False` el QR apunta al entorno de pruebas** (`https://prewww2.aeat.es/...`) y no valida facturas reales.
4. **En Python, `notices(taxpayer_tax_id=None)` devuelve los avisos de todos los obligados tributarios.** Nunca le pases un NIF que pueda faltar; en plantillas, un valor vacío o `None` no muestra ninguno.
5. **`{% verifactu_notices %}` sin argumento muestra los avisos de todos los obligados tributarios.** Úsalo solo en pantallas de operadores; a los usuarios de un cliente, pásale el NIF de su empresa.
6. **Las plantillas por defecto no llevan estilos ni posición.** El tamaño de letra de los textos del QR y el sitio del QR en la factura son responsabilidad tuya (ver abajo).
7. **Los textos de los avisos están en inglés** (`message`) y no pasan por la traducción de Django. Para mostrarlos en español, sobrescribe la plantilla con el número de `unsent` (ver «Mostrar los avisos»).

## Imprimir el QR

```django
{% load verifactu %}
{% verifactu_qr sale %}
```

Imprime «QR tributario:», el código en SVG y, debajo, «Factura verificable en la sede electrónica de la AEAT». El símbolo mide 32 mm, con nivel M de corrección de errores, dentro de una zona en blanco de al menos 3 mm por lado: unos 38 a 40 mm en total. El SVG lleva su tamaño en milímetros.

Orden HAC/1177/2024, art. 20.1 (https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a2-2):

> 1. Una factura, tanto si está impresa en soporte papel como si se trata de la imagen de la misma en soporte digital, incluirá los siguientes elementos que, cumpliendo con los requisitos que se determinen, deberán ser legibles y estar impresos con una resolución apropiada:
> a) Un código «QR», que deberá cumplir con las especificaciones del artículo 21.
> b) En caso de facturas expedidas por «Sistemas de emisión de facturas verificables» o «VERI*FACTU», según los artículos 15 y 16 del Reglamento, la frase «Factura verificable en la sede electrónica de la AEAT» o «VERI*FACTU», que deberá tener un tipo de letra y tamaño bien visibles, similares a los del resto de datos de la factura.

Art. 21.1 (https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a2-3):

> 1. El código «QR» deberá tener un tamaño entre 30x30 y 40x40 milímetros y seguir las especificaciones de la norma ISO/IEC 18004. Para la generación del código «QR» se empleará el nivel M (medio) de corrección de errores. [...]

Colocación, según el «Detalle de las especificaciones técnicas del código «QR» de la factura» (AEAT, v0.5.0, 10/12/2025), apartado 3:

> se deben mantener como mínimo 2 milímetros de espacio vacío (en blanco) alrededor de los cuatro lados del código «QR», recomendándose que sean 6 milímetros.

> El código «QR» se situará al principio de la factura, antes de que empiece el contenido de ésta generado por el sistema informático de facturación, a menos que se justifique la existencia de algún obstáculo para ello [...]. Si la factura ocupara varias páginas, el código «QR» aparecería una única vez, en la primera página.

> Tanto el texto que siempre debe preceder al código «QR», como, en su caso, la frase que habrán de incluir los sistemas «VERI*FACTU» deberán tener un tipo de letra y tamaño legibles, siempre iguales o superiores a los del resto de datos de la factura.

Por tanto: pon la etiqueta al principio de la primera página y da a sus textos una letra al menos tan grande como la del resto de la factura. Para cambiar la maquetación, sobrescribe `django_verifactu/qr.html` en un directorio de `TEMPLATES["DIRS"]` o en una app que vaya antes de `django_verifactu` en `INSTALLED_APPS`. Su contexto es `url`, `svg` (ya marcado como seguro), `label` y `legend`:

```django
<div class="verifactu-qr">
  <div class="verifactu-qr-text">{{ label }}</div>
  {{ svg }}
  <div class="verifactu-qr-text">{{ legend }}</div>
</div>
```

La leyenda corta que admite el art. 20.1.b está en `django_verifactu.aeat.qr.SHORT_LEGEND` (`"VERI*FACTU"`), pero no llega al contexto: si la prefieres, escríbela en tu plantilla.

## QR en PDF y en facturas electrónicas

Si generas el PDF desde HTML, usa la misma etiqueta. Si no, obtén la URL y dibújala:

```python
from io import BytesIO

from django_verifactu.aeat.qr import LABEL, LEGEND, qr_code, qr_svg
from django_verifactu.qr import qr_url


def invoice_qr(sale):
    url = qr_url(sale)  # raises NotRegistered without a valid registration record
    svg = qr_svg(url)  # the same SVG as the template tag, sized in millimetres
    png = BytesIO()
    qr_code(url).save(png, kind="png", scale=10, border=0)  # place it at 32 x 32 mm, blank around
    return url, svg, png.getvalue(), LABEL, LEGEND
```

`qr_code(url)` es un `segno.QRCode` con nivel M. Si lo dibujas tú, respeta los 30 a 40 mm del art. 21.1 y el margen en blanco, y pon `LABEL` encima y `LEGEND` debajo.

Para una factura electrónica estructurada basta la URL, según el art. 20.2 (https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a2-2):

> 2. En caso de tratarse de una factura electrónica, destinada al intercambio de su información de forma estructurada entre sistemas informáticos por medios electrónicos, se deberá incluir como un campo independiente la «URL» contenida en el código «QR», no siendo necesario incluir el propio código «QR».

## El QR tras subsanaciones y anulaciones

El QR sale del último registro de alta no rechazado del objeto en el entorno actual, aunque siga `pending`:

- Puedes imprimir la factura en cuanto `register()` vuelve, sin esperar a la respuesta de la AEAT.
- Tras `amend()`, el QR sigue a la subsanación. Si la AEAT la rechaza, vuelve al alta anterior.
- **Comprobado en el entorno de pruebas:** si una subsanación cambia el importe total, los QR ya impresos dejan de validar; solo coincide el importe nuevo. Según las preguntas frecuentes para desarrolladores de la AEAT (apartado 17), los errores previstos en el Reglamento por el que se regulan las obligaciones de facturación (ROF) se corrigen con facturas rectificativas, y la subsanación queda para errores en datos del registro que «no se ven» en la factura impresa. Una factura rectificativa es otro objeto, con su propio registro y su propio QR; un total negativo conserva el signo (`importe=-121.00`).
- Una factura anulada conserva su QR para reimpresiones. El cotejo responde «no encontrada» cuando la factura «no consta como recibida en la AEAT o se encuentra en estado anulada» (documento técnico del QR, apartado 9.1.2). **Comprobado en el entorno de pruebas:** una factura anulada responde como no encontrada.
- `NotRegistered` (importable desde `django_verifactu.issuing`) salta cuando el objeto no tiene alta, solo tiene altas rechazadas, solo tiene una anulación, o sus registros son del otro entorno.

## Qué avisos exige la Orden

Orden HAC/1177/2024, art. 16.4 (https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a1-8):

> Asimismo, el sistema informático deberá avisar de que se ha producido una incidencia que ha impedido la remisión de todos los registros de facturación generados, indicando cuántos faltan por remitir. Este aviso deberá visualizarse a partir del momento en que se produzca la incidencia que impida la remisión de los registros de facturación y mientras quede alguno de estos por remitir.

Art. 6.f (https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a6):

> f) Cuando el sistema informático detecte cualquier tipo de circunstancia que impida garantizar o que vulnere o pueda vulnerar la integridad e inalterabilidad de los registros de facturación generados, o de su encadenamiento, deberá:
> 1.º Mostrar una alarma que indique claramente este hecho. Dicha alarma no deberá desactivarse hasta que no se pueda volver a garantizar la integridad e inalterabilidad de los siguientes registros de facturación y su encadenamiento.
> 2.º Generar el correspondiente registro de evento que informe sobre el hecho detectado, de acuerdo con lo especificado en el artículo 9.

Art. 7.i y 7.j (https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a7):

> i) Salvo cuando se trate del primer registro de facturación, cada vez que el sistema informático vaya a generar un nuevo registro de facturación, de alta o de anulación, antes deberá comprobar que se cumplen los siguientes requisitos:
> 1.º El último registro de facturación generado está correctamente encadenado.
> 2.º La fecha y hora de generación del último registro de facturación generado no es superior en más de un minuto a la fecha y hora actuales que se utilizarán para fechar el registro de facturación a generar.
> j) Cuando el sistema informático detecte cualquier tipo de circunstancia que impida garantizar o que vulnere o pueda vulnerar la trazabilidad y el encadenamiento de los registros de facturación generados, deberá avisar de ello, procediendo de la misma forma que se indica en el artículo 6.f).

Pero el art. 3 (https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a3) dice de los sistemas VERI*FACTU:

> en tanto actúen como «VERI*FACTU», no les serán de aplicación los artículos 6.b), 6.c), 6.d), 6.e), 6.f), 7.f), 7.h), 7.i), 7.j), 8 y 9 de esta orden.

**Interpretación:** el aviso de registros sin remitir (art. 16.4) es exigible; las alarmas de cadena (arts. 6.f, 7.i y 7.j) no lo son en VERI*FACTU, y la librería las implementa igualmente. El registro de evento del art. 6.f.2.º no existe en la librería (solo VERI*FACTU).

## Mostrar los avisos

```django
{% load verifactu %}
{% verifactu_notices request.user.company.nif %}
```

Ponlo donde tus usuarios emiten facturas, por ejemplo en la plantilla base de esa zona. Muestra dos tipos de aviso:

- **Registros sin remitir**, con cuántos faltan: desde que un envío falla, o desde que los pendientes esperan más de lo que tolera la AEAT (al menos 240 s) por cualquier causa, como un remitente parado, hasta que se remiten todos.
- **Cadena posiblemente rota**: problemas en los 20 registros más recientes de cada cadena (huella o XML alterados, columnas que no coinciden con el XML, eslabones rotos, posiciones que faltan, fechas más de un minuto anteriores a las del registro previo). Cuando el problema queda fuera de esos 20, deja de aparecer; `python manage.py verifactu_verify` revisa las cadenas completas.

Con un NIF, la etiqueta muestra solo los avisos de ese obligado tributario, y ninguno si el valor está vacío o es `None`. Sin argumento, los de todos. Cuesta unas pocas consultas por obligado tributario. Cada aviso se pinta como `<div class="verifactu-notice" role="alert">`, sin estilos: dale en tu CSS un aspecto visible.

Para cambiar el marcado o el idioma, sobrescribe `django_verifactu/notices.html`. Recibe `notices`, una lista de avisos con `taxpayer_tax_id`, `message` (en inglés) y `unsent`: cuántos registros faltan por remitir, o `0` si el aviso es de la cadena. Para tus usuarios en español, por ejemplo en `templates/django_verifactu/notices.html` de tu proyecto:

```django
{% for notice in notices %}
<div class="verifactu-notice" role="alert">
  {% if notice.unsent %}
    Una incidencia ha impedido remitir a la AEAT {{ notice.unsent }} registros de facturación de {{ notice.taxpayer_tax_id }}.
  {% else %}
    Posible problema en el encadenamiento de los registros de facturación de {{ notice.taxpayer_tax_id }}: {{ notice.message }}
  {% endif %}
</div>
{% endfor %}
```

En Python (por ejemplo, para una API), protege el NIF que pueda faltar:

```python
from django_verifactu.notices import notices


def notices_for(tax_id):
    # notices(taxpayer_tax_id=None) returns every taxpayer's notices
    return notices(taxpayer_tax_id=tax_id) if tax_id else []
```

En el admin, los listados de instalaciones, registros y envíos muestran los avisos de todos los obligados tributarios como mensajes de advertencia, solo a quien puede ver esos listados. Para ver los registros de cada factura en su página del admin, añade `django_verifactu.admin.RecordInline` a los `inlines` de su `ModelAdmin`.

## alarm_raised

Antes de generar cada registro, salvo el primero de una cadena, la librería comprueba que el último registro está correctamente encadenado y que su fecha de generación no es más de un minuto posterior a la hora actual. Si falla algo, **el registro se emite igualmente**, cada problema se anota con nivel ERROR en el logger `django_verifactu` y, tras el commit, se envía `alarm_raised(sender=Installation, installation=..., problems=[...])`. Si la transacción se revierte, no se envía.

El receptor corre en el proceso que emite (normalmente una petición web) y no recibe la petición, así que no puede mostrar nada al usuario. Úsalo para alertar a los operadores; a los usuarios les llega el aviso de cadena de `{% verifactu_notices %}`:

```python
import logging

from django.dispatch import receiver

from django_verifactu.signals import alarm_raised

logger = logging.getLogger(__name__)


@receiver(alarm_raised)
def verifactu_alarm(sender, installation, problems, **kwargs):
    for problem in problems:
        logger.critical("VERI*FACTU alarm for %s: %s", installation.taxpayer_tax_id, problem)
```

Conéctalo en `AppConfig.ready()`, como las demás señales (references/envio.md). Una excepción en el receptor no detiene la emisión: Django la registra en el logger `django.dispatch`.
