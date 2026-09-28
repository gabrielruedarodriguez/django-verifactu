# Cambios

## 0.1.0 (2026-09-28)

Primera versión.

- Núcleo de la AEAT sin Django: registros de alta y de anulación con sus huellas, desgloses, terceros, envíos, consultas, códigos QR y los servicios web de la AEAT, validado contra el entorno de pruebas de la AEAT.
- Modelos de Django para instalaciones, registros y envíos, escritos solo por la librería.
- `register`, `amend` y `cancel`, con los indicadores del ciclo de vida obtenidos de los registros guardados.
- `send_pending` y `manage.py verifactu_send`, con control de flujo, incidencias y recuperación de respuestas perdidas.
- La etiqueta de plantilla `verifactu_qr` y `qr_url`.
- Un admin de solo lectura y `RecordInline`.
- Credenciales por obligado tributario, desde los settings o desde una función, renuncia a VERI*FACTU e indicador de múltiples obligados tributarios.
- `query`, `verify` y `manage.py verifactu_verify`.
- `manage.py verifactu_new_installation` para reiniciar una cadena.
- Comprobación de la cadena antes de emitir cada registro, la señal `alarm_raised`, y `notices` con la etiqueta `verifactu_notices` para los registros sin remitir y los problemas de cadena.
