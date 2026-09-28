# Remisión de registros a la AEAT

Lee este archivo cuando tengas que poner en marcha o supervisar la remisión: ejecutar `verifactu_send` como servicio o desde un planificador, entender por qué un registro sigue `pending`, interpretar un `Submission`, conectar receptores a las señales o configurar el log. `register`, `amend` y `cancel` solo guardan registros `pending`; este archivo cubre cómo llegan a la AEAT. El QR y los avisos a los usuarios están en references/qr-y-avisos.md; el marco legal completo, en references/legal.md.

## Trampas

1. **Sin remitente en marcha no se remite nada.** Arranca `verifactu_send --loop` como servicio, o una pasada cada minuto. Nunca una pasada cada hora (ver «Ejecutar el remitente»).
2. **Nunca llames a `send_pending()` dentro de `transaction.atomic()`**, tampoco en una vista con `ATOMIC_REQUESTS`: lanza `RuntimeError` en cuanto le toca hacer un envío (una pasada sin nada que enviar no falla, así que el error aparece de forma intermitente).
3. **No remitas desde la petición web.** Cada lectura de la respuesta puede esperar hasta 120 s, y la AEAT ha tardado más de 30 s en responder a un envío grande. Deja la remisión al proceso remitente.
4. **Conecta los receptores de señales en `AppConfig.ready()`.** `record_answered` y `submission_finished` se envían en el proceso remitente, no en el servidor web.
5. **Solo se remiten los registros del entorno actual.** Con `VERIFACTU["PRODUCTION"] = False` todo va al entorno de pruebas de la AEAT; los registros de un entorno nunca se remiten al otro.
6. **No escribas en `Installation`, `Record`, `Submission` ni `SubmissionLine`.** Solo la librería los escribe; `save()`, `delete()`, `update()` y `create()` lanzan `ImmutableRecord`.
7. **Un `fault` se repite en cada reintento hasta que corrijas su causa** (certificado, contraseña, representación). Los registros esperan `pending` y el aviso de registros sin remitir sigue visible.

## Ejecutar el remitente

Por defecto, un servicio permanente (contacta con la AEAT):

```console
python manage.py verifactu_send --loop
```

- Sin `--loop` hace una sola pasada y termina. `--interval` fija los segundos entre pasadas (por defecto 5) y `--taxpayer NIF` remite un único obligado tributario.
- Las pasadas sin nada que remitir, o que aún deben esperar, no crean envíos: un intervalo corto no incumple el control de flujo.
- Con `--loop`, `SIGTERM` y `SIGINT` lo detienen al acabar la pasada en curso: sus envíos terminan y se guardan.
- Al arrancar ejecuta los system checks: un error `django_verifactu.E00x` impide arrancarlo, y `django_verifactu.W001` (un obligado tributario con credenciales inutilizables) es solo un aviso.

Unidad systemd (ajusta rutas, usuario y módulo de settings):

```ini
[Unit]
Description=VERI*FACTU sender (django-verifactu)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
User=app
WorkingDirectory=/srv/app
EnvironmentFile=/etc/app/env
Environment=DJANGO_SETTINGS_MODULE=config.settings
Environment=PYTHONUNBUFFERED=1
ExecStart=/srv/app/.venv/bin/python manage.py verifactu_send --loop
Restart=always
RestartSec=10
TimeoutStopSec=300

[Install]
WantedBy=multi-user.target
```

- `TimeoutStopSec=300` da margen para acabar la pasada en curso (cada lectura de la respuesta puede esperar hasta 120 s). Si el proceso muere en mitad de un envío, ese envío queda en `sending`, a los 10 minutos se da por perdido (`unknown`) y sus registros se reenvían declarando la incidencia.
- `PYTHONUNBUFFERED=1` hace que cada línea de salida llegue al journal en el momento.
- En un contenedor, usa el mismo comando con reinicio automático y un margen de parada amplio (por ejemplo `stop_grace_period: 5m` en Docker Compose).

Si no puedes tener un servicio, ejecuta una pasada cada minuto desde cron (el entorno de cron debe tener las mismas variables, como la contraseña del certificado):

```console
* * * * * cd /srv/app && .venv/bin/python manage.py verifactu_send >> /var/log/verifactu_send.log 2>&1
```

Con otro planificador (Celery beat, APScheduler...), llama a `django_verifactu.sending.send_pending()` cada 60 s, fuera de toda transacción. Devuelve la lista de `Submission` hechos en esa pasada. No necesitas `flock` ni un único proceso: dos pasadas simultáneas nunca remiten a la vez para el mismo obligado tributario y entorno.

**Por qué nunca cada hora.** El RD 1007/2023, art. 16.1 (https://www.boe.es/buscar/act.php?id=BOE-A-2023-24840#a1-8), define VERI*FACTU como los sistemas usados «para remitir efectivamente por medios electrónicos a la Agencia Estatal de Administración Tributaria de forma continuada, segura, correcta, íntegra, automática, consecutiva, instantánea y fehaciente todos los registros de facturación generados». **Interpretación:** el «al menos una vez cada hora» del art. 16.4 de la Orden es el mínimo para reintentar tras una incidencia, no la cadencia normal. Además, en el entorno de pruebas la AEAT acepta con el error 2004 los registros generados más de 240 s antes de su reloj, y `notices()` cuenta como sin remitir los que esperan más de lo que tolera la AEAT.

## Control de flujo

Orden HAC/1177/2024, art. 16.2 (https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a1-8):

> 2. Los sistemas informáticos «VERI*FACTU» deberán implementar un mecanismo de control de flujo basado en el tiempo de espera entre envíos, el cual tomará inicialmente el valor de 60 segundos, y en el número máximo de registros admitidos en cada envío.
> Los mensajes de respuesta de la Agencia Estatal de Administración Tributaria informarán sobre el valor de este parámetro, el cual deberá ser tenido en cuenta para el siguiente envío.
> El número máximo de registros a remitir en cada envío queda determinado por el diseño de registro incluido en el apartado 2.2 del anexo.
> El funcionamiento será el siguiente:
> a) El sistema informático realiza el envío del primer conjunto de registros de facturación a la Agencia Estatal de Administración Tributaria.
> b) La Agencia Estatal de Administración Tributaria devuelve, entre otros datos, un valor actualizado del parámetro de tiempo de espera «t» entre envíos.
> c) Para poder realizar el siguiente envío, el sistema informático deberá esperar a que transcurran «t» segundos desde el anterior envío o deberá esperar a tener acumulados un número de registros de facturación igual al límite establecido en el diseño de registro para cada envío, la circunstancia que ocurra primero.
> d) El sistema informático realiza un nuevo envío cumpliendo con lo establecido en la letra c). En la respuesta puede recibir una nueva actualización del valor del parámetro «t».

Lo que hace `send_pending()`, por obligado tributario y entorno:

- Guarda el `TiempoEsperaEnvio` de cada respuesta en `Submission.wait_seconds` y no vuelve a enviar hasta que pasan esos segundos desde el final del último envío respondido, salvo que haya 1000 registros pendientes o más.
- Cada envío lleva como máximo 1000 registros (el límite del diseño de registro), en el orden de la cadena. Hace como máximo un envío por obligado tributario en cada pasada, empezando por el que tiene el registro pendiente más antiguo.
- Tras `verifactu_new_installation`, remite primero los pendientes de la cadena anterior.
- **Comprobado en el entorno de pruebas:** la AEAT aceptó envíos seguidos sin esperar. La espera es una obligación de la Orden, no un bloqueo técnico: no la quites.

## Fallos y reintentos

Tras un envío fallido (`fault`, `not_delivered` o `unknown`), el siguiente intento del mismo obligado tributario espera una pausa contada desde el final del último fallo:

| Fallos seguidos desde la última respuesta | Pausa |
|---|---|
| 1 | 1 minuto |
| 2 | 2 minutos |
| 3 | 4 minutos |
| 4 | 8 minutos |
| 5 o más | 15 minutos |

La pausa nunca es menor que el último `TiempoEsperaEnvio` de la AEAT. Así, mientras el remitente esté en marcha, los pendientes se reintentan como mucho cada 15 minutos, salvo que la AEAT pida una espera mayor, dentro de lo que exige la Orden HAC/1177/2024, art. 16.4 (https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a1-8):

> 4. En caso de que alguna incidencia técnica impida la remisión voluntaria en las condiciones indicadas se deberá proceder a la remisión de los registros de facturación en cuanto sea posible, respetando el orden temporal de generación de los registros de facturación. Además, deberá avisar de esta circunstancia indicándolo en los mensajes donde se envíen los correspondientes registros de facturación afectados, dentro del campo habilitado a tal efecto, de acuerdo con las especificaciones dadas en el apartado 4 del anexo.
> El sistema informático deberá reintentar periódicamente, al menos una vez cada hora, el envío de los registros de facturación pendientes de remitir. [...]
> Las incidencias en la remisión voluntaria de registros de facturación agrupados deberán ser debidamente justificadas por el remitente si así se lo requiere la Agencia Estatal de Administración Tributaria.

**Interpretación:** los `Submission` fallidos, con su `response` y sus fechas, documentan la incidencia si la AEAT pide justificarla. Consérvalos.

**Incidencia.** Un registro que ya estuvo en un envío fallido (`fault`, `not_delivered` o `unknown`) se reenvía con `RemisionVoluntaria/Incidencia = S`. Los registros sin intentos previos van en otro envío, sin incidencia: cada envío agrupa solo registros consecutivos en la misma situación. **Comprobado en el entorno de pruebas:** con `Incidencia = S`, un registro antiguo se acepta sin el error 2004. Un registro que esperó porque el remitente no estaba en marcha no tuvo intento previo, así que se remite sin incidencia.

**Respuesta perdida.** Si la petición salió pero la respuesta no llegó o no se pudo leer, el envío queda `unknown` y sus registros se reenvían con incidencia. Para lo que ya guardó, la AEAT responde 3000 (registro duplicado) con el estado del registro guardado. Si el registro estuvo en un envío `unknown`, el remitente adopta ese estado (`accepted`, o `accepted_with_errors` con el código del registro guardado) cuando el 3000 prueba que es el propio registro: un alta que no es subsanación, o una anulación que dejó la factura anulada. Si no, el registro queda `rejected` con 3000. Un 3000 en un registro sin intentos perdidos significa que la AEAT ya tiene esa factura por otro registro (comprobado con una factura registrada por otro sistema). Una respuesta que llega después de dar el envío por perdido también se guarda.

## Aislamiento por obligado tributario

Un problema de un obligado tributario deja su envío en `fault` y los demás siguen en la misma pasada: una entrada ausente en `TAXPAYERS`, un certificado ilegible o una contraseña errónea, un certificado que la AEAT rechaza (redirige a una página de error `erro4011`) o un Fault como 4112 («El titular del certificado debe ser Obligado Emisión, Colaborador Social, Apoderado o Sucesor.»). Solo `not_delivered` (sin conexión con la AEAT, o HTTP 429) detiene la pasada para todos, porque afecta a todos.

## Resultados

`Submission.outcome`:

| Valor | Cuándo | Registros |
|---|---|---|
| `sending` | Envío en curso | Sin cambios |
| `answered` | La AEAT respondió, aunque rechace todos los registros. Guarda `csv`, `wait_seconds` y `response` | Cada uno recibe su estado |
| `fault` | Fault de la AEAT (`error_code`, por ejemplo 4102 o 4112), certificado rechazado, o credenciales o configuración inutilizables | Siguen `pending` |
| `not_delivered` | No se llegó a la AEAT, o respondió HTTP 429 | Siguen `pending` |
| `unknown` | Respuesta perdida o ilegible, o más de 10 minutos en `sending` | Siguen `pending` |

`Record.status` cambia una sola vez, de `pending` al estado de la respuesta:

| Valor | Significado | Qué hacer |
|---|---|---|
| `pending` | Sin respuesta de la AEAT todavía | Nada: el remitente reintenta |
| `accepted` | `Correcto` | Nada |
| `accepted_with_errors` | `AceptadoConErrores`, con `error_code` y `error_description` | Corregir solo si `record.needs_amendment` (es `False` para 2004 y 2009), según references/correcciones.md |
| `rejected` | `Incorrecto` | Corregir según `error_code` y references/correcciones.md |

Cada intento queda en `SubmissionLine` (`record.lines` o `submission.lines`), con la respuesta de la AEAT tal cual: `status`, `error_code`, `error_description` y `duplicate_status`. Tras un duplicado adoptado, `record.error_code` es el del registro guardado; decide siempre con `record`, no con la línea.

## Señales

Todas se envían con `send_robust`: una excepción en tu receptor no afecta a la librería, y Django la registra en el logger `django.dispatch`.

| Señal (`django_verifactu.signals`) | `sender` | Argumentos | Cuándo | Proceso |
|---|---|---|---|---|
| `record_created` | `Record` | `record` | Tras el commit de la transacción que creó el registro; no se envía si hay rollback | El que emite |
| `record_answered` | `Record` | `record`, `line` (`SubmissionLine`) | Con la respuesta ya guardada, una vez por registro respondido | Remitente |
| `submission_finished` | `Submission` | `submission` | Con el envío ya guardado, sea cual sea su `outcome`, tras los `record_answered` | Remitente |
| `alarm_raised` | `Installation` | `installation`, `problems` (`list[str]`) | Tras el commit de un registro emitido después de un problema de cadena | El que emite |

Un envío dado por perdido tras 10 minutos en `sending` no emite `submission_finished`. `alarm_raised` se trata en references/qr-y-avisos.md.

```python
# myapp/receivers.py
import logging

from django.dispatch import receiver

from django_verifactu.models import Record, Submission
from django_verifactu.signals import record_answered, submission_finished

logger = logging.getLogger(__name__)


@receiver(record_answered)
def verifactu_answered(sender, record, line, **kwargs):
    if record.status == Record.Status.REJECTED or record.needs_amendment:
        logger.warning(
            "VERI*FACTU %s %s: %s %s",
            record.invoice_number,
            record.status,
            record.error_code,
            record.error_description,
        )


@receiver(submission_finished)
def verifactu_finished(sender, submission, **kwargs):
    if submission.outcome != Submission.Outcome.ANSWERED:
        logger.error(
            "VERI*FACTU submission %s: %s %s",
            submission.pk,
            submission.outcome,
            submission.error_code,
        )
```

```python
# myapp/apps.py
from django.apps import AppConfig


class MyAppConfig(AppConfig):
    name = "myapp"

    def ready(self):
        from myapp import receivers  # noqa: F401
```

`record.content_object` es tu factura, por si quieres reflejar el estado en tu propio modelo.

## Log y supervisión

- `verifactu_send` escribe una línea por envío en la salida estándar, por ejemplo `B12345674: answered, 3 records`, y nada cuando no envía.
- El logger `django_verifactu` escribe con nivel ERROR cuando un envío no se puede construir o enviar por un fallo inesperado (credenciales, configuración), con la traza, y cuando se emite un registro tras un problema de cadena (`VERI*FACTU chain problem: ...`). `Submission.response` guarda el error sin repetir la contraseña.

```python
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django_verifactu": {"handlers": ["console"], "level": "WARNING"},
        "django.dispatch": {"handlers": ["console"], "level": "ERROR"},
    },
}
```

Para alertas, consulta los modelos (solo lectura):

```python
from django.conf import settings

from django_verifactu.models import Record, Submission

production = settings.VERIFACTU["PRODUCTION"]
pending = Record.objects.filter(
    status=Record.Status.PENDING, installation__production=production
).count()
failed = Submission.objects.filter(installation__production=production).exclude(
    outcome=Submission.Outcome.ANSWERED
)
latest_failures = failed.order_by("-created_at")[:10]
```

Los envíos, registros e instalaciones también se ven en el admin, en solo lectura.
