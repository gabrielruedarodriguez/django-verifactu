# Configuración: settings, credenciales y base de datos

Lee este archivo cuando instales django-verifactu, cuando escribas o revises `settings.VERIFACTU`, cuando conectes los certificados de los obligados tributarios, cuando elijas la base de datos o cuando `manage.py check` muestre un mensaje `django_verifactu.*`. Cada regla sale de `django_verifactu/conf.py`, `django_verifactu/checks.py`, sus tests o los textos citados. Los tests de la integración están en references/pruebas.md; el marco legal, en references/legal.md.

## Trampas

1. **`PRODUCTION` es obligatorio y booleano.** `False` remite al entorno de pruebas de la AEAT y `True`, a producción. Cada valor tiene sus propias cadenas: con el otro valor, sus registros no se remiten, no se verifican, no generan avisos y `qr_url` lanza `NotRegistered`.
2. **Emitir no lee las credenciales.** Solo se leen al remitir, al consultar a la AEAT y en `manage.py check`. `register`, `amend` y `cancel` funcionan aunque el NIF no esté en `TAXPAYERS`; sus registros esperan `pending` hasta que haya credenciales usables.
3. **Un `str` en `certificate` siempre es una ruta.** Un certificado en base64 sin decodificar da `W001` («cannot read the certificate»). Pasa `bytes` o una ruta.
4. **Cambiar `SOFTWARE["system_id"]` bloquea la emisión.** Con registros ya emitidos, `register`, `amend` y `cancel` lanzan `ImproperlyConfigured` hasta que ejecutes `python manage.py verifactu_new_installation <NIF>` para cada obligado tributario (references/verificacion.md). Cambiar `version` no requiere nada.
5. **Varios NIF en `TAXPAYERS` exigen `multiple_taxpayers_possible = True`** (`E003`), salvo que definas `MULTIPLE_TAXPAYERS`.
6. **El NIF del productor debe estar en el censo de la AEAT.** Ninguna comprobación local lo detecta: la AEAT rechaza cada registro con el error 1110 (verificado en el entorno de pruebas).
7. **Con `TAXPAYERS` como función, `manage.py check` no prueba las credenciales.** Solo comprueba que la función se importa. Un certificado o una contraseña erróneos aparecen al remitir, como envíos `fault` de ese obligado tributario.

## Instalación

```python
INSTALLED_APPS = [
    "django.contrib.contenttypes",  # obligatorio: cada registro apunta a tu factura
    # ...
    "django_verifactu",
]
USE_TZ = True  # obligatorio (E001)
```

```console
python manage.py migrate
```

## Ejemplo completo

```python
import os

from django_verifactu.aeat.domain import Party

VERIFACTU = {
    # Sin la variable, False: entorno de pruebas de la AEAT.
    "PRODUCTION": os.environ.get("VERIFACTU_PRODUCTION") == "true",
    "SOFTWARE": {
        "producer": Party("Acme Software SL", tax_id="B12345674"),
        "name": "AcmeERP",
        "system_id": "AE",
        "version": "4.2.0",
        "multiple_taxpayers_possible": False,
    },
    "TAXPAYERS": {
        "B12345674": {
            "name": "Acme SL",
            "certificate": "/run/secrets/acme.p12",  # fuera del repositorio
            "password": os.environ["ACME_P12_PASSWORD"],
        },
    },
    # "MULTIPLE_TAXPAYERS": "myapp.verifactu.several_billings",
    # "TIME_ZONE": "Europe/Madrid",
}
```

Deja `PRODUCTION` en `False` en desarrollo, CI y preproducción. Qué implica activarlo está en references/legal.md.

## `SOFTWARE`

Identifica tu sistema informático de facturación tal como figura en tu declaración responsable (Orden HAC/1177/2024, art. 15, https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138; ver references/legal.md). Lleva exactamente estas cinco claves:

| Clave | Valor | Si no se cumple |
|---|---|---|
| `producer` | `Party` de `django_verifactu.aeat.domain`, con `tax_id` (NIF) o con `foreign_id` (`ForeignId`), nunca ambos | `E003` con [4102], [4109], [1103]... |
| `name` | De 1 a 30 caracteres | `E003` |
| `system_id` | Dos caracteres, letras mayúsculas o dígitos | `E003` ([1177] si no son mayúsculas o dígitos) |
| `version` | De 1 a 50 caracteres | `E003` |
| `multiple_taxpayers_possible` | `bool`: lo que declaras en la letra f) del art. 15.1 | `ImproperlyConfigured` al emitir si hay varios obligados tributarios (ver `MULTIPLE_TAXPAYERS`) |

No añadas `installation_number` ni `multiple_taxpayers`: los pone la librería (`E003` si los incluyes). El número de instalación es un identificador aleatorio nuevo en cada cadena.

Orden HAC/1177/2024, art. 15.1.b), sobre el código identificador: «Este código no podrá coincidir con el de otro sistema informático distinto que pueda producir dicha persona o entidad.»

Las preguntas frecuentes para desarrolladores de la AEAT (versión 1.3, 4-12-2025, apartado 4) explican por qué `version` y `system_id` se tratan distinto: «un cambio en dicha versión (cuando se actualiza, por ejemplo) no significa que el SIF pase a ser otro SIF con Id. distinto, cosa que sí ocurre con los otros 3 campos mencionados».

## `TAXPAYERS`

Un diccionario cuya clave es el NIF del obligado tributario (el `issuer_tax_id` de sus facturas) y cuyo valor tiene los campos de `django_verifactu.conf.Taxpayer`:

| Campo | Tipo | Uso |
|---|---|---|
| `name` | `str`, de 1 a 120 caracteres | `NombreRazon` del obligado tributario en la cabecera de cada envío |
| `certificate` | Ruta (`str` o `Path`) o `bytes` | Certificado PKCS#12 (.p12 o .pfx) que autentica la conexión |
| `password` | `str` | Contraseña del PKCS#12 |
| `seal` | `bool`, por defecto `False` | `True` si es un certificado de sello |
| `representative` | `Party` con NIF, o `None` | Bloque `Representante` de la cabecera |
| `verifactu_end_date` | `date` o `None` | `FechaFinVeriFactu`: renuncia a VERI*FACTU |

Una clave desconocida, un `representative` que no es `Party` o una fecha que no es `date` dan `W001`.

### Certificado y contraseña

Orden HAC/1177/2024, art. 5: «Para remitir los registros de facturación a la sede electrónica de la Agencia Estatal de Administración Tributaria, los sistemas informáticos deberán presentar ante esta la correspondiente identificación electrónica del remitente mediante el uso de los certificados electrónicos válidos en cada momento en la sede electrónica de la Agencia Estatal de Administración Tributaria.»

- Solo PKCS#12. Un PEM da `W001` con «Could not deserialize PKCS12 data».
- Mantén el certificado y la contraseña fuera del repositorio: una ruta a un secreto montado (`/run/secrets/...`) y la contraseña en una variable de entorno o en un fichero de secretos. Si tu almacén de secretos entrega el certificado en base64, decodifícalo: `"certificate": base64.b64decode(os.environ["ACME_P12_BASE64"])`.
- Una ruta se lee cada vez que se necesitan las credenciales. Un certificado renovado en la misma ruta y con la misma contraseña se usa sin reiniciar.
- Los mensajes de `W001` y las respuestas guardadas de los envíos fallidos nunca repiten la contraseña, y la representación de `Taxpayer` oculta certificado y contraseña.
- Un certificado caducado da `W001`. La AEAT rechaza sin procesar un certificado desconocido o caducado (redirección HTTP 302 a `erro4011.html`, verificado): el envío queda `fault`, sus registros siguen `pending` y los demás obligados tributarios siguen remitiendo.

### `seal`, `representative` y `verifactu_end_date`

- **`seal`**: con `True`, la librería usa el servicio web de la AEAT para certificados de sello. No se ha verificado en el entorno de pruebas.
- **`representative`**: Orden HAC/1177/2024, art. 5: «La remisión podrá ser efectuada por el propio obligado tributario o por un tercero que actúe en su representación». Su NIF debe ser válido (`W001` con [4123]). **Interpretación:** úsalo cuando el certificado es de ese tercero, por ejemplo `Party("Gestoría Ejemplo SA", tax_id="A12345674")`. Solo se ha verificado con la empresa como su propio representante; un tercero con apoderamiento real, no.
- **`verifactu_end_date`**: el último día en que el obligado tributario funciona como VERI*FACTU. Orden HAC/1177/2024, art. 17.2: «El funcionamiento como «VERI*FACTU» deberá mantenerse siempre al menos hasta el final del último año en que haya funcionado como tal, es decir, hasta el 31 de diciembre de dicho año.» Art. 17.3: «El primer mensaje en el que se rellene dicho campo informando de la fecha de fin de funcionamiento como «VERI*FACTU» deberá remitirse antes del final del año natural en el que se quiera hacer efectiva la renuncia.» El documento de la AEAT *Validaciones* (versión 1.2.2, apartado 3.1.1) exige que su año sea el del sistema de la AEAT o el anterior, y añade: «A partir del 1 de enero de 2027, el campo FechaFinVeriFactu debe tener el formato 31-12-20XX.» La librería aplica ambas reglas (`W001` con [4120]). La librería solo declara la fecha en cada envío de ese obligado tributario: no deja de emitir ni de remitir después, y no soporta la modalidad NO VERI*FACTU.

### `TAXPAYERS` como función

Para credenciales guardadas en la base de datos o en un almacén de secretos, pon en `TAXPAYERS` la ruta con puntos (un `str`, no la función) de una función `(tax_id) -> Taxpayer | None`:

```python
# myapp/verifactu.py
import os
from pathlib import Path

from django_verifactu.conf import Taxpayer

from myapp.models import Company  # tu modelo


def credentials(tax_id: str) -> Taxpayer | None:
    company = Company.objects.filter(tax_id=tax_id).first()
    if company is None:
        return None
    secrets = Path(os.environ["VERIFACTU_SECRETS_DIR"])
    return Taxpayer(
        name=company.legal_name,
        certificate=secrets / f"{tax_id}.p12",
        password=(secrets / f"{tax_id}.password").read_text().strip(),
    )
```

```python
# settings.py, después de definir VERIFACTU
VERIFACTU["TAXPAYERS"] = "myapp.verifactu.credentials"
```

Se llama en cada envío y en cada consulta a la AEAT de ese obligado tributario. Si devuelve `None` o lanza, el envío queda `fault` y sus registros esperan. Con una función, la librería no sabe cuántos obligados tributarios tienes hasta que emiten: define también `MULTIPLE_TAXPAYERS`.

## `MULTIPLE_TAXPAYERS`

La librería rellena `IndicadorMultiplesOT` en cada registro. Sin `MULTIPLE_TAXPAYERS` vale `S` cuando `TAXPAYERS` es un diccionario con otro NIF, o cuando la base de datos tiene la cadena de otro obligado tributario en el mismo entorno; si no, `N`. Si vale `S` y `SOFTWARE["multiple_taxpayers_possible"]` es `False`, emitir lanza `ImproperlyConfigured`.

En un SaaS la AEAT pide otro cálculo (preguntas frecuentes para desarrolladores, apartado 4): «este valor deberá calcularse de forma independiente por cada usuario del SIF SaaS (no a nivel global del SIF SaaS) y se informará con “S” en todos los registros de facturación (y, en su caso, de evento) de aquellos usuarios que tengan creadas más de una facturación en el SIF SaaS, independientemente del estado de dichas facturaciones (alta, baja…) y de si son de igual o de distinto OEF.»

En ese caso, pon en `MULTIPLE_TAXPAYERS` la ruta con puntos de una función `(tax_id) -> bool` que haga ese cálculo. Se llama en cada emisión, dentro de su transacción, y decide sola el indicador:

```python
# myapp/verifactu.py
from myapp.models import Company  # tu modelo


def several_billings(tax_id: str) -> bool:
    account = Company.objects.get(tax_id=tax_id).account
    # Cuentan también las empresas dadas de baja.
    return Company.objects.filter(account=account).count() > 1
```

## `TIME_ZONE` y `USE_TZ`

- `USE_TZ = True` es obligatorio (`E001`).
- `VERIFACTU["TIME_ZONE"]` (por defecto `Europe/Madrid`) fecha la generación de cada registro y da el «hoy» con el que se validan las fechas de expedición. Es independiente del `TIME_ZONE` de Django y de la zona activa en la petición. Acepta cualquier zona IANA; una zona desconocida da `E003`.
- Orden HAC/1177/2024, art. 7.e): «El sistema informático deberá incorporar a los registros de facturación la fecha y hora exactas del momento en que son generados, de acuerdo al territorio desde donde se expide la correspondiente factura.» **Interpretación:** un despliegue que factura desde Canarias usa `Atlantic/Canary` (verificado: la AEAT la acepta sin avisos). La librería admite una sola zona por despliegue.
- Mantén el reloj del servidor sincronizado: la AEAT acepta con el error 2004 los registros cuya hora de generación se aparta más de 240 s de su reloj (verificado).

## Base de datos

- **PostgreSQL** es la recomendada; los tests de concurrencia de la librería se ejecutan sobre ella.
- **MySQL** funciona con el aislamiento READ COMMITTED que Django configura por defecto. No pongas `"isolation_level": "repeatable read"`: con ese aislamiento, dos primeras emisiones simultáneas de un mismo obligado tributario pueden terminar con `IntegrityError`.
- **SQLite**, solo para desarrollo.
- Los registros viven en la base de datos del objeto que factura. Si tu router envía los modelos de `django_verifactu` a otra base, `register` lanza `ImproperlyConfigured`. El remitente, los avisos y la verificación usan la base que el router da a esos modelos sin instancia: con varias bases de datos, envía `django_verifactu` y `django.contrib.contenttypes` a la misma base que tus facturas.
- Tras restaurar una copia de seguridad, inicia una cadena nueva con `verifactu_new_installation` (references/verificacion.md).

## Comprobaciones del sistema

`python manage.py check` ejecuta estas comprobaciones:

| Id | Causa | Arreglo |
|---|---|---|
| `django_verifactu.E001` | `USE_TZ` no es `True` | `USE_TZ = True` |
| `django_verifactu.E002` | Falta `VERIFACTU` o `PRODUCTION`, o no es un `bool` | `"PRODUCTION": False` (un `bool`, no `"false"`) |
| `django_verifactu.E003` | `SOFTWARE` con claves de más o de menos, valores fuera de límites o productor inválido; `TIME_ZONE` desconocida; o varios NIF en `TAXPAYERS` con `multiple_taxpayers_possible = False` y sin `MULTIPLE_TAXPAYERS` | Corrige el valor que cita el mensaje (tabla de `SOFTWARE`). Para varios NIF, `True` solo si tu declaración responsable lo dice; si no, deja un solo NIF |
| `django_verifactu.E004` | `TAXPAYERS` no es un diccionario ni un `str`, o su función no se importa o no es invocable | Un diccionario, o la ruta con puntos de la función |
| `django_verifactu.E005` | `MULTIPLE_TAXPAYERS` no es un `str`, o su función no se importa o no es invocable | La ruta con puntos de la función |
| `django_verifactu.W001` | Una entrada de `TAXPAYERS` no se puede usar: certificado ilegible o no PKCS#12, contraseña errónea, clave que no es un NIF válido ([4116]), `name` vacío o de más de 120 caracteres, representante sin NIF válido ([4123]), `verifactu_end_date` fuera de plazo ([4120]), campo desconocido, o certificado caducado | Corrige lo que cita el mensaje |

`W001` es un aviso, no un error, para que las credenciales de un obligado tributario nunca impidan remitir los registros de los demás. Mientras persista, los envíos de ese obligado tributario terminan `fault` y sus registros esperan `pending`. Solo se comprueban las entradas de un diccionario; con una función, lee el log `django_verifactu` y los `Submission` con `outcome = "fault"`.
