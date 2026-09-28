# Emitir facturas con `register`

Lee este archivo cuando conectes el modelo de facturas del proyecto con django-verifactu: añadir `VerifactuRecords`, llamar a `register` al expedir y traducir cada factura a `django_verifactu.aeat.domain.Invoice`. Recoge el significado de cada campo, sus códigos (`django_verifactu.aeat.codes`), las reglas que la librería comprueba con el código de error de la AEAT entre paréntesis, y ejemplos que pasan `validate_invoice`. Las excepciones y las respuestas de la AEAT están en references/errores.md; cuándo rectificar, subsanar o anular, en references/correcciones.md; la remisión, en references/envio.md.

## Trampas

1. **Llama a `register` dentro de la transacción que guarda la factura**, después de guardar el objeto y sus líneas. Fuera de `transaction.atomic()` lanza `TransactionManagementError`. El RD 1007/2023, art. 9 (https://www.boe.es/buscar/act.php?id=BOE-A-2023-24840#a9), exige generar el registro de alta «de forma simultánea o inmediatamente anterior a la expedición de cada factura».
2. **Deja que las excepciones de `register` salgan del bloque atómico.** Así se deshace también la factura y nunca queda una factura expedida sin registro. Captúralas fuera (references/errores.md).
3. **Registra solo al expedir y nunca reutilices un número.** Nada de borradores, proformas ni pruebas con `PRODUCTION = True`. La AEAT identifica cada factura por emisor + número + fecha de expedición y responde 3000 a un segundo registro de alta. Preguntas frecuentes para desarrolladores de la AEAT (4-12-2025), apartado 6: «ya NO es posible reutilizar la numeración de ninguna factura expedida, aunque sean facturas expedidas "de prueba"».
4. **Un objeto, una factura.** Cada factura rectificativa es otro objeto con su propio `register`. No cambies el número ni la fecha de un objeto ya registrado: `amend` y `cancel` lanzarían `LifecycleError`.
5. **Importes y tipos siempre en `Decimal`, con dos decimales como máximo; fechas en `date`.** Con un `float`, un `int` o un `datetime`, `register` lanza `TypeError`; con un tercer decimal, `ValueError`. `validate_invoice` no detecta todos estos casos: un `Invoice` solo con `float` o solo con `int` le devuelve `[]`. Redondea con `quantize(Decimal("0.01"))` igual que en la factura impresa.
6. **No indiques `amendment` ni `previous_rejection`**: la librería decide esos indicadores y lanza `ValueError` si los pasas.
7. **NIF en mayúsculas, 9 caracteres, sin espacios ni guiones.** `b76543214` o `B-76543214` dan 1239 en un destinatario y 1123 en el emisor.
8. **Los totales no se indican: se calculan a partir de las líneas**, sin la retención de IRPF (ver «Importes y totales»).

## Vincular el modelo y registrar

```python
# models.py
from django.db import models
from django_verifactu.models import VerifactuRecords

class Sale(models.Model):
    number = models.CharField(max_length=60)
    issue_date = models.DateField()
    customer_name = models.CharField(max_length=120)
    customer_nif = models.CharField(max_length=9)
    description = models.CharField(max_length=500)
    verifactu_records = VerifactuRecords()  # no necesita migración

class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, models.PROTECT, related_name="lines")
    base = models.DecimalField(max_digits=12, decimal_places=2)
    vat_rate = models.DecimalField(max_digits=4, decimal_places=2)
    vat = models.DecimalField(max_digits=12, decimal_places=2)
```

Sin `VerifactuRecords`, `register` lanza `ImproperlyConfigured`. Un objeto con registros no se puede borrar, ni en cascada (`ProtectedError`). `sale.verifactu_records` da sus `Record`. Escribe una única función que traduzca tu factura a `Invoice` y úsala en `register` y en `amend`:

```python
# services.py
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django_verifactu.aeat.domain import Invoice, Party, TaxLine
from django_verifactu.issuing import register

from .models import Sale, SaleLine

def to_invoice(sale: Sale) -> Invoice:
    # Un TaxLine por tipo de IVA: la AEAT admite como máximo 12 (4113).
    totals = defaultdict(lambda: [Decimal("0.00"), Decimal("0.00")])
    for line in sale.lines.all():
        totals[line.vat_rate][0] += line.base
        totals[line.vat_rate][1] += line.vat
    return Invoice(
        issuer_tax_id="B12345674",
        issuer_name="Acme SL",
        invoice_number=sale.number,
        issue_date=sale.issue_date,
        description=sale.description,
        recipients=(Party(sale.customer_name, tax_id=sale.customer_nif),),
        lines=tuple(
            TaxLine(base=base, rate=rate, tax=tax) for rate, (base, tax) in sorted(totals.items())
        ),
    )

def issue_sale(sale_fields: dict, line_fields: list[dict]) -> Sale:
    with transaction.atomic():
        sale = Sale.objects.create(**sale_fields)
        SaleLine.objects.bulk_create(SaleLine(sale=sale, **fields) for fields in line_fields)
        register(sale, to_invoice(sale))
    return sale
```

- Con más datos fiscales por línea, agrupa por impuesto, régimen, calificación o exención, tipo y tipo de recargo.
- Con varios emisores (un SaaS), toma `issuer_tax_id` e `issuer_name` de la empresa de la factura; cada NIF necesita credenciales en `VERIFACTU["TAXPAYERS"]` para remitir, no para emitir. Con varios obligados tributarios, `SOFTWARE["multiple_taxpayers_possible"]` debe ser `True` o `register` lanza `ImproperlyConfigured` (references/errores.md).
- `register` valida (`ValidationError`, sin escribir nada), decide los indicadores, encadena el registro y lo guarda como `Record` en estado `pending`, que devuelve. El código QR ya está disponible; `verifactu_send` lo remite después del commit.

## Campos de `Invoice`

| Campo | Elemento AEAT | Reglas |
|---|---|---|
| `issuer_tax_id` | IDEmisorFactura | NIF válido (1123) |
| `issuer_name` | NombreRazonEmisor | 1 a 120 caracteres, no en blanco (1100) |
| `invoice_number` | NumSerieFactura | Ver «Número de factura» |
| `issue_date` | FechaExpedicionFactura | Ver «Fechas» |
| `description` | DescripcionOperacion | 1 a 500 caracteres, no en blanco (1100) |
| `recipients` | Destinatarios | Tupla de `Party`. Obligatoria en F1, F3 y R1 a R4 (1189), vacía en F2 y R5 (1190), hasta 1000 (4113) |
| `lines` | Desglose | Tupla de 1 a 12 `TaxLine` (4102, 4113) |
| `operation_date` | FechaOperacion | Ver «Fechas» |
| `invoice_type` | TipoFactura | `InvoiceType`, por defecto `F1` |
| `correction_type` | TipoRectificativa | `CorrectionType.SUBSTITUTION` (S) o `DIFFERENCES` (I). Obligatorio en R1 a R5 (1114), prohibido en las demás (1115) |
| `corrected_invoices` | FacturasRectificadas | Tupla de `InvoiceId`, opcional, solo en R1 a R5 (1117) |
| `replaced_invoices` | FacturasSustituidas | Tupla de `InvoiceId`, solo en F3 (1116) |
| `corrected_amounts` | ImporteRectificacion | `CorrectedAmounts`: obligatorio por sustitución (1118), prohibido en otro caso (1119) |
| `simplified_art_72_73` | FacturaSimplificadaArt7273 | No en F2 ni R5 (1183) |
| `without_recipient_art_61d` | FacturaSinIdentifDestinatarioArt61d | Solo F2 y R5 (1185) |
| `coupon` | Cupon | Solo R1 y R5 (1157) |
| `external_reference` | RefExterna | Texto libre para tu propio identificador, hasta 60 caracteres (1253) |
| `issued_by` | EmitidaPorTerceroODestinatario | `IssuedBy.RECIPIENT` (D) exige destinatarios; `IssuedBy.THIRD_PARTY` (T) exige `third_party` (1158) |
| `third_party` | Tercero | `Party`, solo con `THIRD_PARTY` (1155, 1159). NIF válido y distinto del emisor (1178, 1188); nunca IdType 07 (1211) |
| `billing_agreement` | NumRegistroAcuerdoFacturacion | «Número de registro obtenido al enviar la autorización en materia de facturación o de libros registro» |
| `system_agreement` | IdAcuerdoSistemaInformatico | «Identificación del acuerdo (resolución) a que se refiere el artículo 5 del Reglamento» |
| `amendment`, `previous_rejection` | Subsanacion, RechazoPrevio | Nunca los indiques |

## Tipos de factura

Elegir el tipo es una decisión fiscal del emisor. Descripciones de la lista L2 del anexo de la Orden HAC/1177/2024 (https://www.boe.es/buscar/act.php?id=BOE-A-2024-22138#an):

- `F1` «Factura (art. 6, 7.2 y 7.3 del RD 1619/2012).»; `F2` «Factura Simplificada y Facturas sin identificación del destinatario art. 6.1.d) RD 1619/2012.»; `F3` «Factura emitida en sustitución de facturas simplificadas facturadas y declaradas.»
- `R1` «Factura Rectificativa (Error fundado en derecho y art. 80 Uno Dos y Seis LIVA).»; `R2` «Factura Rectificativa (art. 80.3).»; `R3` «Factura Rectificativa (art. 80.4).»; `R4` «Factura Rectificativa (Resto).»; `R5` «Factura Rectificativa en facturas simplificadas.»
- F2 y R5 van sin destinatarios; el resto los exige. En F2, la suma de bases y cuotas no puede superar 3.000 € más 10 € de margen (1150), salvo con `without_recipient_art_61d=True` o `billing_agreement`.

## Número de factura

- De 1 a 60 caracteres (1104), sin espacios al principio ni al final (1104). Comprobado con la AEAT: guarda el número recortado, pero su cotejo del QR no lo recorta, así que el QR de esa factura nunca se encontraría. Los espacios interiores se conservan.
- Solo ASCII imprimible, códigos 32 a 126 (1130): nada de `ñ`, `º`, `€` ni tildes.
- Sin `"`, `'`, `<`, `>` ni `=` (1287).
- Distingue mayúsculas: la librería trata `A-1` y `a-1` como facturas distintas, y el cotejo del QR de la AEAT también las distingue (comprobado). Usa siempre la misma cadena en `register`, `amend`, `cancel`, `InvoiceId` y el documento impreso.

## Fechas

- `issue_date`: no posterior a hoy en la zona `VERIFACTU["TIME_ZONE"]` (por defecto `Europe/Madrid`) (1112), ni anterior al 1 de enero de 2024 (1152). Comprobado con la AEAT: acepta desde esa fecha, aunque el texto de 1152 cita el 28 de octubre de 2024.
- `operation_date`: indícala solo si difiere; el diseño de registro la describe como «Fecha en la que se ha realizado la operación siempre que sea diferente a la fecha de expedición». No puede ser futura (1173) ni posterior a `issue_date` (1146), salvo con los regímenes 14 y 15; ni anterior a hoy menos 20 años (1134); ni de un año posterior al siguiente (1125). Los tipos con vigencia limitada se comprueban con ella, o con `issue_date` si falta.

## Importes y totales

- Cuota total = Σ(`tax` + `surcharge`); importe total = Σ(`base` + `tax` + `surcharge`). La librería los calcula siempre; no hay campo para indicarlos. Con un importe total de 100.000.000 € o más en valor absoluto añade `Macrodato`.
- Negativos admitidos, por ejemplo en rectificativas por diferencias. `tax` y la base llevan el mismo signo (1143) y `tax` no se aparta más de 10 € de base × tipo / 100 (1142), salvo en rectificativas por diferencias y en R2 y R3.
- RD 1007/2023, art. 10.2 (https://www.boe.es/buscar/act.php?id=BOE-A-2023-24840#a1-2): «Todos los importes monetarios que consten en el registro de facturación de alta deberán expresarse en euros.»
- Preguntas frecuentes para desarrolladores, apartado 20: «la retención a cuenta del IRPF o IS que vaya en factura, no se incluirá en el registro de facturación». Lo mismo dice de los suplidos: no pases al registro ni la retención ni los suplidos.

## `TaxLine`: una línea del desglose

| Campo | Elemento AEAT | Por defecto | Reglas |
|---|---|---|---|
| `base` | BaseImponibleOimporteNoSujeto | Obligatorio | Base, o importe no sujeto en N1 y N2 |
| `rate` | TipoImpositivo | `None` | IVA: 0, 2, 4, 5, 7.5, 10 o 21 (1124). El 5 solo del 1-7-2022 al 30-9-2024 (1194); el 2 y el 7.5, del 1-10-2024 al 31-12-2024 (1235, 1236). Obligatorio en S1 (1208) |
| `tax` | CuotaRepercutida | `None` | Obligatorio en S1 (1208) |
| `tax_type` | Impuesto | `TaxType.VAT` | `VAT` 01, `IPSI` 02, `IGIC` 03, `OTHER` 05 |
| `regime` | ClaveRegimen | `RegimeKey.GENERAL` | Obligatorio con IVA e IGIC (1245) y, en la librería, con IPSI (2009); `None` con `OTHER` (1260) |
| `qualification` | CalificacionOperacion | `S1` | Exactamente uno de `qualification` y `exemption` (1195, 1196) |
| `exemption` | OperacionExenta | `None` | Línea exenta: `qualification=None` y sin `rate`, `tax` ni recargo (1238) |
| `base_at_cost` | BaseImponibleACoste | `None` | Solo régimen 06, IPSI u `OTHER` (1257); el 06 la exige (1202) |
| `surcharge_rate`, `surcharge` | TipoRecargoEquivalencia, CuotaRecargoEquivalencia | `None` | Van juntos (1284), solo en S1 (1281). Recargos: 0, 0.26, 0.5, 0.62, 1, 1.4, 1.75 o 5.2 (1127). Parejas IVA/recargo: 21/5.2 o 1.75 (1162), 10/1.4 (1163), 7.5/1 (1169), 4/0.5 (1164), 2/0.26 (1166). Con el 5, 0.5 del 1-7-2022 al 31-12-2022 (1167) o 0.62 del 1-1-2023 al 30-9-2024 (1168), y cualquier otro da 1160. Con el 0, solo 0 (1277), del 1-1-2023 al 30-9-2024 (1165) |

Códigos, con las listas del anexo de la Orden HAC/1177/2024:

- `OperationQualification` (L9): `S1` «Operación Sujeta y No exenta - Sin inversión del sujeto pasivo.», `S2` «Operación Sujeta y No exenta - Con Inversión del sujeto pasivo.» (`rate` y `tax` a 0, 1198; nunca en F2 ni R5, 1197), `N1` «Operación No Sujeta artículo 7, 14, otros.», `N2` «Operación No Sujeta por Reglas de localización.». En N1 y N2 con IVA, sin `rate`, `tax` ni recargo (1237).
- `ExemptionCause` (L10): exenta por el artículo 20 (`E1`), 21 (`E2`), 22 (`E3`), 23 y 24 (`E4`) o 25 (`E5`), y `E6` «Exenta por otros.»; `E7` y `E8`, solo con IGIC (1182). E2 y E3 no van con el régimen general (1199). E5 con IVA no admite destinatarios con `tax_id` (1289).
- `RegimeKey` (L8A y L8B): `GENERAL` 01, `EXPORT` 02 (solo líneas exentas, 1286), `USED_GOODS` 03, `INVESTMENT_GOLD` 04, `TRAVEL_AGENCIES` 05, `ENTITY_GROUP` 06, `CASH_ACCOUNTING` 07, `OTHER_INDIRECT_TAX` 08 (N2, 1252), `TRAVEL_AGENCY_MEDIATION` 09, `THIRD_PARTY_COLLECTIONS` 10, `BUSINESS_PREMISES_RENTAL` 11 (IVA al 21, 1206), `PUBLIC_WORKS_PENDING_TAX` 14, `SUCCESSIVE_SUPPLY_PENDING_TAX` 15, `ONE_STOP_SHOP` 17, `EQUIVALENCE_SURCHARGE` 18, `AGRICULTURE` 19, `SIMPLIFIED` 20. Con IGIC e IPSI los códigos 17 a 21 significan otra cosa: usa los alias `IGIC_*` e `IPSI_*`, que comparten valor.

## Partes, referencias e importes rectificados

- `Party(name, tax_id=None, foreign_id=None)`: `name` de 1 a 120 caracteres; exactamente uno de `tax_id` (NIF) y `foreign_id` (4102).
- `ForeignId(id_type, number, country=None)`, con `IdType` (L7): `VAT_NUMBER` 02 NIF-IVA, `PASSPORT` 03, `OFFICIAL_ID` 04 documento oficial del país de residencia, `RESIDENCE_CERTIFICATE` 05, `OTHER_DOCUMENT` 06, `NOT_REGISTERED` 07 no censado.
  - `number` hasta 20 caracteres (1100). `country` en ISO 3166-1 alfa-2 y mayúsculas, obligatorio salvo con 02 (1111). Con 02, el número lleva el prefijo del país (`FR12345678901`) y su estructura (1239), y `country`, si lo pones, coincide con el prefijo (1122). Comprobado con la AEAT: rechaza (1239) un NIF-IVA bien formado que no está en VIES.
  - Con `country="ES"` solo 03 o 07 (1126). 07 exige `ES` (1126) y el NIF de una persona física (1239). La AEAT lo reserva a NIF correctos «pero no figuren censados en la AEAT» y lo acepta con el error 2001 (documento «Validaciones» de la AEAT para VERI*FACTU, 4.3.1).
- `InvoiceId(issuer_tax_id, invoice_number, issue_date)`: identifica una factura rectificada o sustituida con exactamente los mismos valores con que se registró. Comprobado con la AEAT: no verifica que exista (una F3 que cita una factura inexistente se acepta), así que un error aquí pasa desapercibido.
- `CorrectedAmounts(base, tax)`: `BaseRectificada` y `CuotaRectificada`, que el diseño de registro describe como «Base imponible de la factura» y «Cuota repercutida o soportada de la factura». Interpretación: los importes de la factura rectificada; confírmalo con el asesor fiscal.
- **Hueco conocido:** `CorrectedAmounts` no tiene campo para `CuotaRecargoRectificado`, que el diseño de registro describe como «Cuota recargo de equivalencia de la factura.». Una rectificativa por sustitución no puede informar la cuota de recargo de equivalencia rectificada. Por diferencias no hace falta, porque `ImporteRectificacion` solo va con sustitución.

## Ejemplos

Todos pasan `validate_invoice(invoice, date(2026, 9, 28)) == []`; ninguno contacta con la AEAT. Las rectificativas y la F3 son facturas nuevas: cada una va en su propio objeto con su propio `register`.

```python
from datetime import date
from decimal import Decimal

from django_verifactu.aeat.codes import CorrectionType, ExemptionCause, IdType, InvoiceType
from django_verifactu.aeat.codes import OperationQualification
from django_verifactu.aeat.domain import CorrectedAmounts, ForeignId, Invoice, InvoiceId
from django_verifactu.aeat.domain import Party, TaxLine
from django_verifactu.aeat.validation import validate_invoice

ISSUER = {"issuer_tax_id": "B12345674", "issuer_name": "Acme SL"}
CUSTOMER = Party("Talleres Norte SL", tax_id="B76543214")
TODAY = date(2026, 9, 28)
ORIGINAL = InvoiceId("B12345674", "A-2026/0001", date(2026, 9, 15))

# F1 al 21 %: cuota total 21.00, importe total 121.00.
f1 = Invoice(
    **ISSUER, invoice_number="A-2026/0001", issue_date=date(2026, 9, 15),
    description="Servicios de consultoría", recipients=(CUSTOMER,),
    lines=(TaxLine(base=Decimal("100.00"), rate=Decimal("21"), tax=Decimal("21.00")),),
)
# Varios tipos: una línea por tipo. Destinatario persona física.
several = Invoice(
    **ISSUER, invoice_number="A-2026/0002", issue_date=TODAY, description="Suministros varios",
    recipients=(Party("Lucía Martín Gómez", tax_id="12345678Z"),),
    lines=(
        TaxLine(base=Decimal("200.00"), rate=Decimal("21"), tax=Decimal("42.00")),
        TaxLine(base=Decimal("50.00"), rate=Decimal("10"), tax=Decimal("5.00")),
        TaxLine(base=Decimal("30.00"), rate=Decimal("4"), tax=Decimal("1.20")),
    ),
)
# F2 simplificada: sin destinatarios.
f2 = Invoice(
    **ISSUER, invoice_number="T-2026/0153", issue_date=date(2026, 9, 20),
    description="Venta en tienda", invoice_type=InvoiceType.F2, recipients=(),
    lines=(TaxLine(base=Decimal("8.26"), rate=Decimal("21"), tax=Decimal("1.73")),),
)
# Línea exenta (E1) junto a una sujeta: qualification=None y sin rate ni tax.
exempt = Invoice(
    **ISSUER, invoice_number="A-2026/0003", issue_date=TODAY,
    description="Servicios según detalle", recipients=(CUSTOMER,),
    lines=(
        TaxLine(base=Decimal("300.00"), qualification=None, exemption=ExemptionCause.E1),
        TaxLine(base=Decimal("40.00"), rate=Decimal("21"), tax=Decimal("8.40")),
    ),
)
# Destinatario con NIF-IVA y línea no sujeta por reglas de localización (N2). La calificación
# depende de la operación, no del país. Sin NIF-IVA: ForeignId(IdType.PASSPORT, "123456789", "US").
foreign = Invoice(
    **ISSUER, invoice_number="A-2026/0004", issue_date=TODAY, description="Desarrollo de software",
    recipients=(Party("Dupont SARL", foreign_id=ForeignId(IdType.VAT_NUMBER, "FR12345678901")),),
    lines=(TaxLine(base=Decimal("1500.00"), qualification=OperationQualification.N2),),
)
# R1 por diferencias: solo la diferencia, aquí negativa. Importe total -24.20.
r1_differences = Invoice(
    **ISSUER, invoice_number="R-2026/0001", issue_date=TODAY,
    description="Descuento sobre la factura A-2026/0001", recipients=(CUSTOMER,),
    invoice_type=InvoiceType.R1, correction_type=CorrectionType.DIFFERENCES,
    corrected_invoices=(ORIGINAL,),
    lines=(TaxLine(base=Decimal("-20.00"), rate=Decimal("21"), tax=Decimal("-4.20")),),
)
# R1 por sustitución: las líneas llevan los importes nuevos completos.
r1_substitution = Invoice(
    **ISSUER, invoice_number="R-2026/0002", issue_date=TODAY,
    description="Rectifica la factura A-2026/0001", recipients=(CUSTOMER,),
    invoice_type=InvoiceType.R1, correction_type=CorrectionType.SUBSTITUTION,
    corrected_invoices=(ORIGINAL,),
    corrected_amounts=CorrectedAmounts(base=Decimal("100.00"), tax=Decimal("21.00")),
    lines=(TaxLine(base=Decimal("80.00"), rate=Decimal("21"), tax=Decimal("16.80")),),
)
# F3: sustituye la simplificada T-2026/0153.
f3 = Invoice(
    **ISSUER, invoice_number="A-2026/0005", issue_date=TODAY,
    description="Factura en sustitución del tique T-2026/0153", recipients=(CUSTOMER,),
    invoice_type=InvoiceType.F3,
    replaced_invoices=(InvoiceId("B12345674", "T-2026/0153", date(2026, 9, 20)),),
    lines=(TaxLine(base=Decimal("8.26"), rate=Decimal("21"), tax=Decimal("1.73")),),
)

for invoice in (f1, several, f2, exempt, foreign, r1_differences, r1_substitution, f3):
    assert validate_invoice(invoice, TODAY) == []
```

`FR12345678901` solo ilustra el formato (ver VIES en «Partes»). Preguntas frecuentes para desarrolladores, apartado 27: la F3 «Siempre debe llevar el destinatario de la misma» y debe incorporar «la identificación de la/s factura/s simplificada/s a la/s que canjea».
