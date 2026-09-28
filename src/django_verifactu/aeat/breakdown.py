from datetime import date
from decimal import Decimal

from django_verifactu.aeat.codes import (
    CorrectionType,
    ExemptionCause,
    InvoiceType,
    OperationQualification,
    RegimeKey,
    TaxType,
)
from django_verifactu.aeat.domain import Invoice, TaxLine
from django_verifactu.aeat.violations import Violation

S1, S2, N1, N2 = (OperationQualification(code) for code in ("S1", "S2", "N1", "N2"))
MAX_LINES = 12
_TAX_TOLERANCE = Decimal("10.00")
_VAT_RATES = {Decimal(rate) for rate in ("0", "2", "4", "5", "7.5", "10", "21")}
_TEMPORARY_VAT_RATES = {
    Decimal("5"): (date(2022, 7, 1), date(2024, 9, 30), 1194),
    Decimal("2"): (date(2024, 10, 1), date(2024, 12, 31), 1235),
    Decimal("7.5"): (date(2024, 10, 1), date(2024, 12, 31), 1236),
}
_SURCHARGE_PAIRS = {
    Decimal(21): ({Decimal("5.2"), Decimal("1.75")}, 1162),
    Decimal(10): ({Decimal("1.4")}, 1163),
    Decimal("7.5"): ({Decimal(1)}, 1169),
    Decimal(4): ({Decimal("0.5")}, 1164),
    Decimal(2): ({Decimal("0.26")}, 1166),
}
_SURCHARGE_RATES = {
    Decimal(rate) for rate in ("0", "0.26", "0.5", "0.62", "1", "1.4", "1.75", "5.2")
}
_VAT_REGIMES = {RegimeKey(code) for code in [f"{n:02}" for n in range(1, 12)] + ["14", "15"]} | {
    RegimeKey(code) for code in ("17", "18", "19", "20")
}
_REGIMES = {
    TaxType.VAT: _VAT_REGIMES,
    TaxType.IGIC: _VAT_REGIMES | {RegimeKey.IGIC_SIMPLIFIED},
    TaxType.IPSI: {RegimeKey(code) for code in ("01", "08", "11", "18", "19", "20")},
}
_PENDING_TAX = (RegimeKey.PUBLIC_WORKS_PENDING_TAX, RegimeKey.SUCCESSIVE_SUPPLY_PENDING_TAX)
_PUBLIC_WORKS_TYPES = {InvoiceType(code) for code in ("F1", "R1", "R2", "R3", "R4")}
_CASH_ACCOUNTING_EXCLUDED = {ExemptionCause(code) for code in ("E2", "E3", "E4", "E5")}


def check_breakdown(invoice: Invoice, tax_date: date) -> list[Violation]:
    check_tax = invoice.correction_type is not CorrectionType.DIFFERENCES and (
        invoice.invoice_type not in (InvoiceType.R2, InvoiceType.R3)
    )
    if not invoice.lines:
        return [Violation(4102, "the invoice needs at least one breakdown line")]
    if len(invoice.lines) > MAX_LINES:
        return [Violation(4113, f"an invoice holds at most {MAX_LINES} breakdown lines")]
    violations = []
    for line in invoice.lines:
        violations += _check_classification(line, invoice)
        violations += _check_regime(line, invoice)
        violations += _check_vat_amounts(line, tax_date, check_tax)
        violations += _check_surcharge(line, tax_date)
    return violations


def has_pending_tax(invoice: Invoice) -> bool:
    return any(
        line.regime in _PENDING_TAX and line.tax_type in (TaxType.VAT, TaxType.IGIC)
        for line in invoice.lines
    )


def _check_classification(line: TaxLine, invoice: Invoice) -> list[Violation]:
    qualification, exemption = line.qualification, line.exemption
    if qualification is None and exemption is None:
        return [Violation(1195, "a line needs a qualification or an exemption")]
    if qualification is not None and exemption is not None:
        return [Violation(1196, "a line cannot have both a qualification and an exemption")]
    charged = any(
        value is not None for value in (line.rate, line.tax, line.surcharge_rate, line.surcharge)
    )
    if exemption is not None:
        return _check_exemption(line, invoice, charged)
    violations = []
    if qualification is S2:
        if invoice.invoice_type in (InvoiceType.F2, InvoiceType.R5):
            violations.append(Violation(1197, "reverse charge (S2) is not for F2 or R5"))
        if line.rate != 0 or line.tax != 0:
            violations.append(Violation(1198, "reverse charge (S2) needs rate 0 and tax 0"))
    if qualification in (N1, N2) and line.tax_type is TaxType.VAT and charged:
        violations.append(Violation(1237, "not subject VAT lines carry no rate, tax or surcharge"))
    if qualification in (N1, N2) and line.tax_type is not TaxType.VAT and line.tax:
        violations.append(Violation(1207, "only S1 lines charge tax"))
    if qualification is S1 and line.base_at_cost is None and None in (line.rate, line.tax):
        violations.append(Violation(1208, "S1 lines need rate and tax"))
    return violations


def _check_exemption(line: TaxLine, invoice: Invoice, charged: bool) -> list[Violation]:
    exemption = line.exemption
    violations = []
    if exemption in (ExemptionCause.E7, ExemptionCause.E8) and line.tax_type is not TaxType.IGIC:
        violations.append(Violation(1182, "E7 and E8 are IGIC exemptions"))
    if charged:
        violations.append(Violation(1238, "exempt lines carry no rate, tax or surcharge"))
    general = line.regime is RegimeKey.GENERAL and line.tax_type in (TaxType.VAT, TaxType.IGIC)
    if general and exemption in (ExemptionCause.E2, ExemptionCause.E3):
        violations.append(Violation(1199, "the general regime excludes E2 and E3"))
    national = any(recipient.tax_id is not None for recipient in invoice.recipients)
    if exemption is ExemptionCause.E5 and line.tax_type is TaxType.VAT and national:
        violations.append(Violation(1289, "E5 recipients must be identified with a foreign id"))
    return violations


def _check_regime(line: TaxLine, invoice: Invoice) -> list[Violation]:
    regime, tax_type = line.regime, line.tax_type
    if tax_type is TaxType.OTHER:
        return [Violation(1260, "tax type 05 has no regime")] if regime is not None else []
    if regime is None and tax_type is TaxType.IPSI:
        # Verified live: the AEAT accepts it with the admissible error 2009 instead of 1245.
        return [Violation(2009, "IPSI lines need a regime")]
    if regime is None:
        return [Violation(1245, "VAT and IGIC lines need a regime")]
    if regime not in _REGIMES[tax_type]:
        return [Violation(1246, f"regime {regime.value} is not valid for tax {tax_type.value}")]
    violations = []
    if line.base_at_cost is not None and regime is not RegimeKey.ENTITY_GROUP:
        if tax_type is not TaxType.IPSI:
            violations.append(Violation(1257, "base_at_cost is for regime 06, IPSI or tax 05"))
    if tax_type is not TaxType.IPSI:
        violations += _check_vat_igic_regime(line, invoice)
    return violations


def _check_vat_igic_regime(line: TaxLine, invoice: Invoice) -> list[Violation]:
    regime, qualification, kind = line.regime, line.qualification, invoice.invoice_type
    if regime is RegimeKey.EXPORT and qualification is not None:
        return [Violation(1286, "exports (02) are exempt lines only")]
    if regime is RegimeKey.USED_GOODS and qualification not in (None, S1):
        return [Violation(1200, "used goods (03) lines are S1 or exempt")]
    if regime is RegimeKey.INVESTMENT_GOLD and qualification not in (None, S2):
        return [Violation(1201, "investment gold (04) lines are S2 or exempt")]
    if regime is RegimeKey.ENTITY_GROUP and (
        kind in (InvoiceType.F2, InvoiceType.F3, InvoiceType.R5) or line.base_at_cost is None
    ):
        return [Violation(1202, "entity group (06) needs base_at_cost and no F2, F3 or R5")]
    if regime is RegimeKey.CASH_ACCOUNTING and (
        qualification in (S2, N1, N2)
        or line.exemption in _CASH_ACCOUNTING_EXCLUDED
    ):
        return [Violation(1203, "cash accounting (07) excludes S2, N1, N2 and E2-E5")]
    if regime is RegimeKey.OTHER_INDIRECT_TAX and qualification is not N2:
        return [Violation(1252, "regime 08 lines are N2")]
    if regime is RegimeKey.THIRD_PARTY_COLLECTIONS and (
        qualification is not N1
        or kind is not InvoiceType.F1
        or any(recipient.tax_id is None for recipient in invoice.recipients)
    ):
        return [Violation(1205, "third party collections (10) are N1 F1 invoices to NIFs")]
    rental = regime is RegimeKey.BUSINESS_PREMISES_RENTAL and line.tax_type is TaxType.VAT
    if rental and line.rate != 21:
        return [Violation(1206, "business premises rental (11) is taxed at 21 %")]
    if regime is RegimeKey.PUBLIC_WORKS_PENDING_TAX:
        return _check_public_works(invoice)
    ipsi_operations = regime is RegimeKey.IGIC_IPSI_OPERATIONS and line.tax_type is TaxType.IGIC
    if ipsi_operations and qualification is not N2:
        return [Violation(1293, "IGIC regime 20 lines are N2")]
    return []


def _check_public_works(invoice: Invoice) -> list[Violation]:
    violations = []
    operation_date = invoice.operation_date
    if operation_date is None or operation_date <= invoice.issue_date:
        violations.append(Violation(1147, "regime 14 needs an operation_date after issue_date"))
    if invoice.invoice_type not in _PUBLIC_WORKS_TYPES:
        violations.append(Violation(1148, "regime 14 is for F1 and R1-R4 invoices"))
    if not all(r.tax_id and r.tax_id[0] in "PQSV" for r in invoice.recipients):
        violations.append(Violation(1149, "regime 14 recipients are public bodies (P, Q, S, V)"))
    return violations


def _check_vat_amounts(line: TaxLine, tax_date: date, check_tax: bool) -> list[Violation]:
    if line.qualification is not S1 or line.rate is None:
        return []
    violations = []
    if line.tax_type is TaxType.VAT:
        if line.rate not in _VAT_RATES:
            violations.append(Violation(1124, f"VAT rate {line.rate} is not allowed"))
        elif line.rate in _TEMPORARY_VAT_RATES:
            start, end, code = _TEMPORARY_VAT_RATES[line.rate]
            if not start <= tax_date <= end:
                message = f"VAT rate {line.rate} only applies {start}..{end}"
                violations.append(Violation(code, message))
    if not check_tax or line.tax is None:
        return violations
    at_cost = line.base_at_cost is not None
    base = line.base_at_cost if at_cost else line.base
    if abs(line.tax - base * line.rate / 100) > _TAX_TOLERANCE:
        code = 1144 if at_cost else 1142
        violations.append(Violation(code, "tax differs from base * rate / 100 by more than 10"))
    if line.tax and base and (line.tax < 0) != (base < 0):
        violations.append(Violation(1140 if at_cost else 1143, "tax and base must share the sign"))
    return violations


def _check_surcharge(line: TaxLine, tax_date: date) -> list[Violation]:
    rate, amount = line.surcharge_rate, line.surcharge
    if rate is None and amount is None:
        return []
    if rate is None or amount is None:
        return [Violation(1284, "surcharge_rate and surcharge go together")]
    if line.qualification is not S1:
        return [Violation(1281, "only S1 lines carry an equivalence surcharge")]
    if line.tax_type is not TaxType.VAT:
        return []
    if rate not in _SURCHARGE_RATES:
        return [Violation(1127, f"surcharge rate {rate} is not allowed")]
    if line.rate == 0:
        return _zero_rate_surcharge(rate, tax_date)
    if line.rate == 5:
        return _five_rate_surcharge(rate, tax_date)
    allowed, code = _SURCHARGE_PAIRS.get(line.rate, (None, None))
    if allowed is not None and rate not in allowed:
        return [Violation(code, f"surcharge rate {rate} does not match VAT rate {line.rate}")]
    return []


# Verified live: the code depends on the surcharge sent, and VAT 0 % never accepts 0.26
# (the catalogued rule 1170 is not applied).
def _zero_rate_surcharge(rate: Decimal, tax_date: date) -> list[Violation]:
    if rate != 0:
        return [Violation(1277, "VAT 0 % only takes a 0 surcharge")]
    if not date(2023, 1, 1) <= tax_date <= date(2024, 9, 30):
        return [Violation(1165, "VAT 0 % took surcharge 0 from 2023-01-01 to 2024-09-30 only")]
    return []


def _five_rate_surcharge(rate: Decimal, tax_date: date) -> list[Violation]:
    if rate == Decimal("0.5"):
        in_window = date(2022, 7, 1) <= tax_date <= date(2022, 12, 31)
        return [] if in_window else [Violation(1167, "VAT 5 % took 0.5 in 2022 H2 only")]
    if rate == Decimal("0.62"):
        in_window = date(2023, 1, 1) <= tax_date <= date(2024, 9, 30)
        return [] if in_window else [Violation(1168, "VAT 5 % took 0.62 in 2023-2024 only")]
    return [Violation(1160, "VAT 5 % takes surcharge 0.5 or 0.62")]
