# Marco legal: qué exige la ley y qué cubre django-verifactu

Lee este archivo antes de poner en producción un sistema informático de facturación (SIF) que use django-verifactu, al redactar su declaración responsable y cuando alguien pregunte si el sistema cumple, quién responde ante la AEAT o desde cuándo es obligatorio. Recoge qué exige la normativa al SIF que construyes, qué parte cubre la librería y qué queda de tu lado. Las citas son literales y proceden del BOE, de documentos de la AEAT o de la licencia de la librería. Lo marcado como **Interpretación** no aparece en esos textos. Nada de esto es asesoramiento jurídico: para un caso concreto, remite a un asesor fiscal.

## Trampas

1. **El productor del SIF eres tú (o tu cliente), no django-verifactu.** La librería es un componente y no publica una declaración responsable propia. La tuya debe mencionarla con su versión exacta (ver «Declaración responsable»).
2. **`VERIFACTU["PRODUCTION"] = False` remite al entorno de pruebas**, y el código QR apunta a `https://prewww2.aeat.es/...`. Con facturas reales, ningún registro llega a la AEAT de producción y el QR impreso remite al cotejo del entorno de pruebas.
3. **Remitir en producción es optar por VERI*FACTU al menos hasta el 31 de diciembre de ese año** (RD 1007/2023, art. 16.5; Orden HAC/1177/2024, art. 17.2, citados abajo). **Interpretación:** poner `VERIFACTU["PRODUCTION"] = True` y arrancar el remitente es «iniciar sistemáticamente la remisión».
4. **La letra e) de tu declaración responsable debe decir «S».** La librería escribe siempre `TipoUsoPosibleSoloVerifactu` = `S` en los registros. No la uses en un SIF que pueda expedir facturas sin remitir sus registros: la AEAT exige a ese SIF indicar «N» (ver abajo).
5. **Sin remitente no hay remisión.** Nada se envía si `verifactu_send --loop` (o `send_pending()` cada minuto) no está en marcha, y la Orden exige reintentar al menos una vez cada hora.
6. **El aviso de registros sin remitir es obligatorio.** El admin de la librería lo muestra encima de sus listados, pero tus usuarios solo lo ven si pintas `{% verifactu_notices %}` donde trabajan.
7. **Dónde va el QR en la factura lo decides tú.** `{% verifactu_qr sale %}` dibuja el código, el texto que lo precede y la leyenda, pero no su posición ni el tamaño de letra del resto de la factura.
8. **Actualizar django-verifactu afecta a tu declaración responsable.** **Interpretación** de la FAQ para desarrolladores, apartado 5 (citada abajo), que pide mencionar la versión concreta del componente: fija la versión exacta en tus dependencias (por ejemplo `django-verifactu==0.2.0`) y actualiza la librería y la declaración a la vez.

## Quién responde: Ley 58/2003, General Tributaria

Art. 29.2.j (https://www.boe.es/buscar/act.php?id=BOE-A-2003-23186#a29):

> j) La obligación, por parte de los productores, comercializadores y usuarios, de que los sistemas y programas informáticos o electrónicos que soporten los procesos contables, de facturación o de gestión de quienes desarrollen actividades económicas, garanticen la integridad, conservación, accesibilidad, legibilidad, trazabilidad e inalterabilidad de los registros, sin interpolaciones, omisiones o alteraciones de las que no quede la debida anotación en los sistemas mismos. [...]

Art. 201 bis (https://www.boe.es/buscar/act.php?id=BOE-A-2003-23186#a2-2):

> 1. Constituye infracción tributaria la fabricación, producción y comercialización de sistemas y programas informáticos o electrónicos que soporten los procesos contables, de facturación o de gestión por parte de las personas o entidades que desarrollen actividades económicas, cuando concurra cualquiera de las siguientes circunstancias: [...]
> e) no cumplan con las especificaciones técnicas que garanticen la integridad, conservación, accesibilidad, legibilidad, trazabilidad e inalterabilidad de los registros, así como su legibilidad por parte de los órganos competentes de la Administración Tributaria, en los términos del artículo 29.2.j) de esta Ley;
> f) no se certifiquen, estando obligado a ello por disposición reglamentaria, los sistemas fabricados, producidos o comercializados.
>
> 2. Constituye infracción tributaria la tenencia de los sistemas o programas informáticos o electrónicos que no se ajusten a lo establecido en el artículo 29.2.j) de esta Ley, cuando los mismos no estén debidamente certificados teniendo que estarlo por disposición reglamentaria o cuando se hayan alterado o modificado los dispositivos certificados.

> 4. La infracción señalada en el apartado 1 anterior se sancionará con multa pecuniaria fija de 150.000 euros, por cada ejercicio económico en el que se hayan producido ventas y por cada tipo distinto de sistema o programa informático o electrónico que sea objeto de la infracción. No obstante, las infracciones de la letra f) del apartado 1 de este artículo se sancionarán con multa pecuniaria fija de 1.000 euros por cada sistema o programa comercializado en el que se produzca la falta del certificado.
> La infracción señalada en el apartado 2 anterior, se sancionará con multa pecuniaria fija de 50.000 euros por cada ejercicio, cuando se trate de la infracción por la tenencia de sistemas o programas informáticos o electrónicos que no estén debidamente certificados, teniendo que estarlo por disposición reglamentaria, o se hayan alterado o modificado los dispositivos certificados.

El apartado 1 afecta a quien fabrica, produce o comercializa el sistema; el apartado 2, a quien lo tiene.

## Ámbito y fechas: RD 1007/2023 (RRSIF)

Art. 3 (https://www.boe.es/buscar/act.php?id=BOE-A-2023-24840#a3):

> 1. El presente Reglamento se aplicará a los obligados tributarios que se indican a continuación, que utilicen sistemas informáticos de facturación, aunque solo los usen para una parte de su actividad:
> a) Los contribuyentes del Impuesto sobre Sociedades. [...]
> b) Los contribuyentes del Impuesto sobre la Renta de las Personas Físicas que desarrollen actividades económicas.
> c) Los contribuyentes del Impuesto sobre la Renta de no Residentes que obtengan rentas mediante establecimiento permanente.
> d) Las entidades en régimen de atribución de rentas que desarrollen actividades económicas, sin perjuicio de la atribución de rendimientos que corresponda efectuar a sus miembros.
> 2. El presente Reglamento también se aplicará a los productores y comercializadores de los sistemas informáticos a que se refiere el artículo 1 de este Reglamento en las cuestiones relativas a sus respectivas actividades de producción y comercialización [...]
> 3. El presente Reglamento no se aplicará a los contribuyentes que lleven los libros registros en los términos establecidos en el apartado 6 del artículo 62 del Reglamento del Impuesto sobre el Valor Añadido, aprobado por el Real Decreto 1624/1992, de 29 de diciembre.

Fechas. Disposición final cuarta (https://www.boe.es/buscar/act.php?id=BOE-A-2023-24840#df-4):

> No obstante, los obligados tributarios a que se refiere el artículo 3.1.a) deberán tener adaptados los sistemas informáticos a las características y requisitos establecidos en este reglamento y en su normativa de desarrollo antes del 1 de enero de 2027. El resto de obligados tributarios mencionados en el artículo 3.1 deberán tener operativos los citados sistemas informáticos antes del 1 de julio de 2027.
> Los obligados tributarios del artículo 3.2, en relación con sus actividades de producción y comercialización de los sistemas informáticos, deberán ofrecer sus productos plenamente adaptados al reglamento en el plazo máximo de nueve meses desde la entrada en vigor de la orden ministerial a que se refiere la disposición final tercera este real decreto, [...]

Esa redacción es la del texto consolidado «Última actualización, publicada el 03/12/2025», que procede de la disposición final 1 del Real Decreto-ley 15/2025, de 2 de diciembre (BOE-A-2025-24446). Antes la modificó el Real Decreto 254/2025. El BOE advierte: «Este texto consolidado es de carácter informativo y no tiene valor jurídico.» Las fechas ya han cambiado: comprueba la redacción vigente en el BOE antes de afirmarlas. La Orden HAC/1177/2024 entró en vigor el 29/10/2024, según su ficha en el BOE.

## VERI*FACTU: RD 1007/2023, art. 16, y Orden HAC/1177/2024, arts. 3 y 17

RD art. 16 (https://www.boe.es/buscar/act.php?id=BOE-A-2023-24840#a1-8):

> 1. Aquellos sistemas informáticos indicados en la letra a) del artículo 7 de este Reglamento que, cumpliendo con todas las obligaciones que impone este Reglamento y de acuerdo a las especificaciones técnicas que se establezcan, sean utilizados por el obligado tributario para remitir efectivamente por medios electrónicos a la Agencia Estatal de Administración Tributaria de forma continuada, segura, correcta, íntegra, automática, consecutiva, instantánea y fehaciente todos los registros de facturación generados tendrán la consideración de «Sistemas de emisión de facturas verificables» o «Sistemas VERI*FACTU».

> 3. Los «Sistemas de emisión de facturas verificables» no tendrán la obligación de realizar la firma electrónica de los registros de facturación a la que se refiere el artículo 12 de este Reglamento, siendo suficiente con que calculen la huella o «hash» de dichos registros.

> 5. Se entenderá que un obligado tributario opta por un «Sistema de emisión de facturas verificables» por el hecho de iniciar sistemáticamente la remisión de registros de facturación a la sede electrónica de la Agencia Estatal de Administración Tributaria, en los términos del apartado 1 de este artículo.
> La opción en el uso de los «Sistemas de emisión de facturas verificables» se prolongará, al menos, hasta la finalización del año natural en el que se haya producido, de forma efectiva, el primer envío de los registros de facturación.

Orden art. 3 (https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a3):

> [...] en tanto actúen como «VERI*FACTU», no les serán de aplicación los artículos 6.b), 6.c), 6.d), 6.e), 6.f), 7.f), 7.h), 7.i), 7.j), 8 y 9 de esta orden.

Orden art. 17.2 (https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a1-9):

> 2. El funcionamiento como «VERI*FACTU» deberá mantenerse siempre al menos hasta el final del último año en que haya funcionado como tal, es decir, hasta el 31 de diciembre de dicho año.

Por el art. 3, la comprobación previa del encadenamiento y las alarmas de integridad y encadenamiento (arts. 6.f, 7.i y 7.j) no son exigibles mientras el SIF actúe como VERI*FACTU. django-verifactu hace igualmente la comprobación y avisa del problema, pero no genera registros de evento (art. 6.f.2.º). La AEAT admite hacerlo de forma voluntaria: «Lo mismo cabe decir de las funcionalidades de comprobación/detección de anomalías en cuanto a la obligatoriedad de implementarlas (SIF "DUAL") o no (SIF "SOLO VERI*FACTU") y, [...] ponerlas operativas (obligatorio si se usa en modo "NO VERI*FACTU") o no (si se usa en modo "VERI*FACTU", aunque voluntariamente se permite).» (Aclaraciones a dudas de los desarrolladores, v1.3, apartado 15, nota 1). La misma nota: «El productor de un SIF que solo puede actuar exclusivamente en modo VERI*FACTU ("SOLO VERI*FACTU"), no está obligado a implementar en él un registro de eventos». El aviso de registros sin remitir del art. 16.4 sí es exigible.

## Declaración responsable: RD art. 13 y Orden art. 15

RD art. 13 (https://www.boe.es/buscar/act.php?id=BOE-A-2023-24840#a1-5):

> 1. Corresponderá a la persona o entidad productora del sistema informático certificar, mediante una declaración responsable, que el sistema informático cumple con lo dispuesto en el artículo 29.2.j) de la Ley 58/2003, General Tributaria, así como con lo dispuesto en este Reglamento y en las especificaciones que, en su desarrollo, se aprueben mediante orden ministerial.
> 2. La declaración responsable deberá constar por escrito y de modo visible en el propio sistema informático en cada una de sus versiones, así como para el cliente y el comercializador en el momento de la adquisición del producto.

El apartado 3 obliga al productor o comercializador a «guardar y conservar las declaraciones responsables de todas las versiones de los sistemas informáticos producidos o comercializados».

Orden art. 15 (https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#a1-7): la declaración «comenzará con el título «DECLARACIÓN RESPONSABLE DEL SISTEMA INFORMÁTICO DE FACTURACIÓN»» y contendrá las letras a) a l) en ese orden, cada dato precedido del texto que lo describe. Relación con tu configuración:

| Letra (Orden art. 15.1) | De dónde sale |
|---|---|
| a) Nombre del sistema informático | `VERIFACTU["SOFTWARE"]["name"]` (`NombreSistemaInformatico`) |
| b) Código identificador | `SOFTWARE["system_id"]` (`IdSistemaInformatico`), el mismo que llevan los registros |
| c) Versión completa | `SOFTWARE["version"]` |
| d) Componentes y funcionalidades | Tu sistema, más django-verifactu con su versión exacta |
| e) Solo VERI*FACTU | «S»: la librería escribe siempre `TipoUsoPosibleSoloVerifactu` = `S` |
| f) Varios obligados tributarios | `SOFTWARE["multiple_taxpayers_possible"]` (`TipoUsoPosibleMultiOT`) |
| g) Tipos de firma | Solo si no se usa como VERI*FACTU (RD art. 16.3 exime de firmar) |
| h), i) Productor y su NIF | `SOFTWARE["producer"]`, por ejemplo `Party("Acme Software SL", tax_id="B12345674")` |
| j) Dirección postal | No está en la configuración |
| k) Manifestación de cumplimiento | Texto de la Orden, art. 15.1.k |
| l) Fecha y lugar de firma | No está en la configuración |

Para la letra d), obtén la versión instalada así:

```python
from importlib.metadata import version

print(version("django-verifactu"))
```

Orden art. 15.3 y 15.4:

> 3. La declaración responsable deberá encontrarse disponible de manera legible e individualizada dentro del propio sistema informático a que se refiere y ser accesible por el usuario de forma rápida, fácil e intuitiva. [...]
> 4. En caso de que el sistema informático sea ampliado con otros componentes, hardware o software, producidos por otras personas o entidades distintas a quien ha producido dicho sistema informático, estas deberán aportar las correspondientes declaraciones responsables de todas y cada una de las ampliaciones realizadas, en sus diferentes versiones.
> Asimismo, cuando el propio sistema informático esté formado por varios componentes, hardware o software, producidos por diferentes personas o entidades, todas ellas deberán aportar las correspondientes declaraciones responsables de sus componentes, en sus diferentes versiones.

AEAT, preguntas frecuentes sobre la certificación de los sistemas informáticos (declaración responsable), actualizadas a 21 de julio de 2026:

- «Si se usa software de facturación de código abierto ¿quién hace la declaración responsable?»: «La empresa que efectúe la programación del código o integre partes de otro software, ya sea o no de código abierto, debe realizar la declaración responsable, incorporar los datos obligatorios e indicar qué componentes utiliza. En el caso de que utilice código abierto, se hará responsable del funcionamiento del mismo, incluyendo los sistemas de seguridad exigidos para preservar la integridad, conservación, accesibilidad, legibilidad, trazabilidad e inalterabilidad de los registros.»
- Desarrollo propio para uso propio: «Si el software hubiera sido desarrollado por la propia empresa, será esta la que deba certificarlo, cumpliendo para ello lo que establece el mencionado artículo 13 y su normativa de desarrollo.»
- SIF solo VERI*FACTU: «Sí, la obligación de certificación se aplica a todos los SIF.»
- Letra e): un SIF que no esté diseñado para funcionar siempre y exclusivamente como VERI*FACTU «deberá indicar una “N” tanto en la Certificación (letra e) como en el campo correspondiente».

Aclaraciones a dudas de los desarrolladores (AEAT, v1.3, 4 de diciembre de 2025), apartado 5, sobre un componente de facturación (CF) de un tercero integrado en el componente principal (CPF):

> a) Si el CF fuera producido por un tercero (que, como se ha dicho, también debería certificarlo con su propia DR, por sus funcionalidades de facturación que implementen requisitos del RRSIF), [...] en la DR del CPF debería indicarse que invoca indefectiblemente dichos CF (con mención expresa a la versión concreta usada de esos CF), y también cómo lo hace, cuándo y para qué (es decir, la parte de requisitos que implementan los CF).

**Interpretación.** django-verifactu encaja en la definición de componente de facturación de la Orden (art. 1.2.b): genera, encadena y remite los registros y forma la URL del QR. La Orden (art. 15.4) y la FAQ para desarrolladores (apartado 5) prevén que el productor de un componente aporte su propia declaración responsable, y django-verifactu no la publica. La FAQ sobre código abierto hace responsable de su funcionamiento a quien lo integra. Describe en la letra d) de tu declaración qué hace la librería, su versión exacta y cómo, cuándo y para qué la invoca tu sistema. Si eso no basta para tu caso, consulta a un asesor.

## Qué cubre la librería y qué haces tú

| Exigencia | django-verifactu | Tú |
|---|---|---|
| Registro de alta «de forma simultánea o inmediatamente anterior a la expedición de cada factura» (RD art. 9) | `register()` genera el registro en tu transacción; fuera de una lanza `TransactionManagementError` | Llama a `register()` en la transacción que guarda la factura, antes de entregarla |
| Corrección o anulación mediante un registro adicional posterior, sin alterar el original (RD art. 8.2.a) | `amend()` y `cancel()` añaden registros; el ORM impide modificar o borrar registros y envíos (`ImmutableRecord`) y borrar un objeto con registros | No escribas en sus tablas por SQL |
| Huella, encadenamiento y una cadena por obligado tributario (Orden arts. 6.a, 7.a a 7.d y 2.b) | Automáticos | Nada |
| Fecha y hora «de acuerdo al territorio desde donde se expide la correspondiente factura», con huso horario (Orden art. 7.e y 7.g) | Fecha los registros en `VERIFACTU["TIME_ZONE"]` (por defecto `Europe/Madrid`), no en el `TIME_ZONE` de Django: una zona por despliegue | Fija `VERIFACTU["TIME_ZONE"]` (por ejemplo `Atlantic/Canary`) |
| Remisión continuada e instantánea (RD art. 16.1; Orden art. 16.1) | `verifactu_send` y `send_pending()` | Ejecútalo como servicio permanente |
| Control de flujo: tiempo de espera o número máximo de registros (Orden art. 16.2) | Respeta la espera que devuelve la AEAT o envía al llegar a 1000 pendientes | Nada |
| Reintentar «al menos una vez cada hora», marcar la incidencia y avisar «indicando cuántos faltan por remitir» (Orden art. 16.4) | Reintenta tras 1 a 15 minutos, declara `Incidencia` al reenviar y `notices()` cuenta los registros sin remitir | Muestra `{% verifactu_notices %}` y mantén vivo el remitente |
| Justificar las incidencias si la AEAT lo requiere (Orden art. 16.4) | Conserva cada envío (`Submission`) con su resultado, su CSV y la respuesta | Conserva esas tablas |
| Certificados electrónicos válidos; remisión por el obligado tributario o su representante (Orden art. 5) | `TAXPAYERS` (`certificate`, `password`, `seal`, `representative`); `manage.py check` avisa (`W001`) de certificados inutilizables o caducados | Aporta certificados válidos y las facultades de representación |
| Con varios obligados tributarios, «visualizar, claramente y en todo momento, la información identificativa del obligado tributario» y avisar de que hay más de uno (Orden art. 2.d) | Cadenas separadas e `IndicadorMultiplesOT` | Muéstralo en tu interfaz: la librería no lo hace |
| QR de 30x30 a 40x40 mm con nivel M (Orden art. 21.1) y la frase «Factura verificable en la sede electrónica de la AEAT» (Orden art. 20.1.b) | `{% verifactu_qr sale %}`: 32 mm, al menos 3 mm de zona de silencio, nivel M, «QR tributario:» encima y la frase debajo | Colócalo como pide la AEAT (abajo) |
| Factura electrónica estructurada: la URL del QR como campo independiente (Orden art. 20.2) | `django_verifactu.qr.qr_url(obj)` | Inclúyela en el formato que intercambias |
| Alarmas de integridad y encadenamiento (Orden arts. 6.f, 7.i y 7.j), no exigibles en VERI*FACTU | Comprueba el último registro antes de cada uno nuevo, anota el error en el log `django_verifactu`, envía `alarm_raised` y nunca detiene la facturación; `notices()` muestra los problemas de los 20 registros más recientes de cada cadena. No genera registros de evento | Opcional: conecta `alarm_raised` a tus alertas |
| Declaración responsable (RD art. 13; Orden art. 15) | No la proporciona | Redáctala, fírmala, muéstrala en el sistema y consérvala por versión |
| Renuncia a VERI*FACTU (Orden art. 17.3) | `verifactu_end_date` rellena `FechaFinVeriFactu` en los envíos | A partir de esa fecha necesitas un SIF NO VERI*FACTU: la librería no lo cubre |

Colocación del QR, según el documento de la AEAT «Detalle de las especificaciones técnicas del código «QR» de la factura» (v0.5.0, 10/12/2025, apartado 3): «El código «QR» se situará al principio de la factura, antes de que empiece el contenido de ésta generado por el sistema informático de facturación, a menos que se justifique la existencia de algún obstáculo para ello». «Si la factura ocupara varias páginas, el código «QR» aparecería una única vez, en la primera página.» El texto previo y la frase «deberán tener un tipo de letra y tamaño legibles, siempre iguales o superiores a los del resto de datos de la factura».

Sobre las respuestas de la AEAT, Orden art. 16.3: «La respuesta afirmativa por parte de la Agencia Estatal de Administración Tributaria no implica que los registros de facturación remitidos sean completamente válidos, ni impide posteriores validaciones por parte de la Agencia Estatal de Administración Tributaria.»

## Lista previa a producción

- [ ] Declaración responsable de tu SIF firmada, con django-verifactu y su versión exacta en la letra d) y «S» en la letra e), visible dentro del sistema (RD art. 13.2; Orden art. 15.3) y conservada para cada versión (RD art. 13.3).
- [ ] `VERIFACTU["SOFTWARE"]` coincide con las letras a), b), c), f), h) e i) de la declaración. Si cambias `system_id`, la librería exige iniciar una cadena nueva con `verifactu_new_installation`.
- [ ] Versión de django-verifactu fijada en tus dependencias.
- [ ] `python manage.py check` sin errores `django_verifactu.E00x` ni avisos `django_verifactu.W001`.
- [ ] Certificado electrónico válido de cada obligado tributario, o de un representante con las facultades necesarias (Orden art. 5).
- [ ] `VERIFACTU["TIME_ZONE"]` del territorio desde el que se expiden las facturas, y reloj del servidor sincronizado. En el entorno de pruebas, la AEAT marcó con el error 2004 los registros cuya fecha de generación se alejaba más de 240 segundos de su reloj.
- [ ] `VERIFACTU["PRODUCTION"] = True` solo en el despliegue que expide facturas reales, sabiendo que eso es optar por VERI*FACTU al menos hasta el 31 de diciembre de ese año (trampa 3).
- [ ] `python manage.py verifactu_send --loop` como servicio permanente (systemd, contenedor o supervisor), con reinicio automático y supervisión. Contacta con la AEAT.
- [ ] `{% verifactu_notices %}` visible donde trabajan los usuarios (Orden art. 16.4), con el NIF de su empresa si el sistema lleva varios obligados tributarios.
- [ ] Obligado tributario activo siempre visible, y aviso de que hay varios, si es el caso (Orden art. 2.d).
- [ ] `{% verifactu_qr sale %}` al principio de la primera página de cada factura, con la leyenda, y la URL como campo propio en las facturas electrónicas estructuradas (Orden art. 20).
- [ ] Registros `rejected` y `record.needs_amendment` atendidos, según el error, con una factura rectificativa, `amend` o `cancel` (FAQ para desarrolladores, apartado 17), por ejemplo conectando `record_answered`.
- [ ] `python manage.py verifactu_verify --aeat` programado de forma periódica (termina con error si encuentra un problema). Es una comprobación que ofrece la librería, no una exigencia legal para VERI*FACTU: la Orden (art. 3) excluye la comprobación de la cadena (art. 6.e). Contacta con la AEAT.

## Responsabilidad de django-verifactu

django-verifactu se distribuye «tal cual» bajo la licencia Apache 2.0. Sección 7: «Licensor provides the Work (and each Contributor provides its Contributions) on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND [...]. You are solely responsible for determining the appropriateness of using or redistributing the Work and assume any risks associated with Your exercise of permissions under this License.» La sección 8 limita la responsabilidad por daños.

La librería se ha validado únicamente contra el entorno de pruebas de la AEAT. Quien la integra produce el sistema informático de facturación, emite su declaración responsable y responde de su funcionamiento. Díselo así al desarrollador cuando pregunte si django-verifactu cumple la normativa: la librería implementa requisitos concretos, pero quien certifica el cumplimiento es el productor del SIF.

Fuentes, copias locales: Ley 58/2003 (texto consolidado, última actualización publicada el 21/12/2024), RD 1007/2023 (texto consolidado, 03/12/2025), Orden HAC/1177/2024 (texto inicial, 28/10/2024), las FAQ de la sede de la AEAT citadas y los documentos técnicos de la AEAT indicados en cada cita.
