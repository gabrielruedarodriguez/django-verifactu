from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from django_verifactu.aeat.codes import (
    ExemptionCause,
    IdType,
    InvoiceType,
    OperationQualification,
    RegimeKey,
    TaxType,
)
from django_verifactu.aeat.domain import ForeignId, Party, TaxLine
from django_verifactu.aeat.validation import validate_invoice
from tests.aeat.sample import INVOICE

TODAY = date(2026, 9, 24)
S1, S2, N1, N2 = (OperationQualification(code) for code in ("S1", "S2", "N1", "N2"))
PUBLIC_BODY = (Party("Agencia Tributaria", tax_id="Q2826000H"),)
FOREIGN = (Party("Kunde", foreign_id=ForeignId(IdType.PASSPORT, "AB123456", "FR")),)


def taxed(**fields):
    return TaxLine(**({"base": Decimal(100), "rate": Decimal(21), "tax": Decimal(21)} | fields))


def untaxed(**fields):
    return TaxLine(**({"base": Decimal(100), "qualification": None} | fields))


def codes(*lines, **changes):
    invoice = replace(INVOICE, lines=lines, **changes)
    return [violation.code for violation in validate_invoice(invoice, TODAY)]


def test_between_1_and_12_lines():
    assert codes() == [4102]
    assert codes(*[taxed()] * 12) == []
    assert codes(*[taxed()] * 13) == [4113]


def test_standard_line_is_valid():
    assert codes(taxed()) == []


def test_qualification_or_exemption():
    assert codes(untaxed(exemption=ExemptionCause.E1)) == []
    assert codes(untaxed()) == [1195]
    assert codes(TaxLine(base=Decimal(100), exemption=ExemptionCause.E1)) == [1196]


def test_exempt_lines_carry_no_rate_or_tax():
    assert codes(taxed(qualification=None, exemption=ExemptionCause.E1)) == [1238]


def test_e7_and_e8_are_igic_only():
    assert codes(untaxed(exemption=ExemptionCause.E7)) == [1182]
    assert codes(untaxed(exemption=ExemptionCause.E7, tax_type=TaxType.IGIC)) == []


def test_general_regime_excludes_e2_and_e3():
    assert codes(untaxed(exemption=ExemptionCause.E2)) == [1199]
    assert codes(untaxed(exemption=ExemptionCause.E2, regime=RegimeKey.EXPORT)) == []


def test_e5_needs_foreign_recipients():
    assert codes(untaxed(exemption=ExemptionCause.E5)) == [1289]
    assert codes(untaxed(exemption=ExemptionCause.E5), recipients=FOREIGN) == []


def test_reverse_charge():
    assert codes(taxed(qualification=S2, rate=Decimal(0), tax=Decimal(0))) == []
    assert codes(taxed(qualification=S2)) == [1198]
    reverse_charge = taxed(qualification=S2, rate=Decimal(0), tax=Decimal(0))
    assert codes(reverse_charge, invoice_type=InvoiceType.F2, recipients=()) == [1197]


def test_not_subject_vat_lines_carry_no_rate_or_tax():
    assert codes(untaxed(qualification=N1)) == []
    assert codes(untaxed(qualification=N1, rate=Decimal(21), tax=Decimal(0))) == [1237]
    igic = untaxed(qualification=N1, rate=Decimal(7), tax=Decimal(0), tax_type=TaxType.IGIC)
    assert codes(igic) == []


def test_only_s1_charges_tax():
    assert codes(untaxed(qualification=N2, tax_type=TaxType.IGIC, tax=Decimal(5))) == [1207]


def test_s1_needs_rate_and_tax():
    assert codes(taxed(rate=None)) == [1208]


def test_regime_presence_depends_on_the_tax():
    assert codes(taxed(regime=None)) == [1245]
    assert codes(taxed(regime=None, tax_type=TaxType.IGIC)) == [1245]
    assert codes(taxed(regime=None, tax_type=TaxType.IPSI)) == [2009]
    assert codes(taxed(tax_type=TaxType.OTHER)) == [1260]
    assert codes(taxed(tax_type=TaxType.OTHER, regime=None)) == []


@pytest.mark.parametrize(
    ("tax_type", "regime", "expected"),
    [
        (TaxType.VAT, RegimeKey.IGIC_SIMPLIFIED, [1246]),
        (TaxType.IGIC, RegimeKey.IGIC_SIMPLIFIED, []),
        (TaxType.IPSI, RegimeKey.GENERAL, []),
        (TaxType.IPSI, RegimeKey.CASH_ACCOUNTING, [1246]),
    ],
)
def test_regime_lists_per_tax(tax_type, regime, expected):
    assert codes(taxed(tax_type=tax_type, regime=regime)) == expected


def test_export_is_exempt_only():
    assert codes(taxed(regime=RegimeKey.EXPORT)) == [1286]


def test_used_goods_regime_is_s1_or_exempt():
    assert codes(untaxed(regime=RegimeKey.USED_GOODS, qualification=N1)) == [1200]
    assert codes(untaxed(regime=RegimeKey.USED_GOODS, exemption=ExemptionCause.E1)) == []


def test_investment_gold_is_s2_or_exempt():
    assert codes(taxed(regime=RegimeKey.INVESTMENT_GOLD)) == [1201]
    reverse_charge = {"qualification": S2, "rate": Decimal(0), "tax": Decimal(0)}
    gold = taxed(regime=RegimeKey.INVESTMENT_GOLD, **reverse_charge)
    assert codes(gold) == []


def test_entity_group_needs_base_at_cost():
    assert codes(taxed(regime=RegimeKey.ENTITY_GROUP)) == [1202]
    assert codes(taxed(regime=RegimeKey.ENTITY_GROUP, base_at_cost=Decimal(100))) == []


def test_cash_accounting_limits():
    reverse_charge = taxed(qualification=S2, rate=Decimal(0), tax=Decimal(0))
    assert codes(replace(reverse_charge, regime=RegimeKey.CASH_ACCOUNTING)) == [1203]


def test_other_indirect_tax_regime_is_n2():
    assert codes(taxed(regime=RegimeKey.OTHER_INDIRECT_TAX)) == [1252]
    assert codes(untaxed(regime=RegimeKey.OTHER_INDIRECT_TAX, qualification=N2)) == []


def test_third_party_collections_are_n1():
    assert codes(untaxed(regime=RegimeKey.THIRD_PARTY_COLLECTIONS, qualification=N1)) == []
    assert codes(taxed(regime=RegimeKey.THIRD_PARTY_COLLECTIONS)) == [1205]


def test_business_premises_rental_is_21_percent():
    rental = taxed(regime=RegimeKey.BUSINESS_PREMISES_RENTAL, rate=Decimal(10), tax=Decimal(10))
    assert codes(rental) == [1206]


def test_public_works_with_pending_tax():
    works = taxed(regime=RegimeKey.PUBLIC_WORKS_PENDING_TAX)
    assert codes(works, recipients=PUBLIC_BODY) == [1147]
    later = {"recipients": PUBLIC_BODY, "operation_date": date(2026, 12, 1)}
    assert codes(works, **later) == []
    assert codes(works, **later | {"recipients": INVOICE.recipients}) == [1149]


def test_igic_ipsi_operations_are_n2():
    ipsi_operations = taxed(tax_type=TaxType.IGIC, regime=RegimeKey.IGIC_IPSI_OPERATIONS)
    assert codes(ipsi_operations) == [1293]


def test_base_at_cost_only_for_entity_group_ipsi_and_other():
    assert codes(taxed(base_at_cost=Decimal(100))) == [1257]
    assert codes(taxed(base_at_cost=Decimal(100), tax_type=TaxType.IPSI)) == []


def test_vat_rate_list_does_not_apply_to_igic():
    assert codes(taxed(tax_type=TaxType.IGIC, rate=Decimal(7), tax=Decimal(7))) == []


@pytest.mark.parametrize(
    ("rate", "surcharge_rate", "expected"),
    [
        ("21", "5.2", []),
        ("21", "1.75", []),
        ("21", "1.4", [1162]),
        ("10", "1.4", []),
        ("10", "5.2", [1163]),
        ("4", "0.5", []),
        ("4", "1.4", [1164]),
        ("0", "0.26", [1277]),
        ("0", "0", [1165]),
        ("21", "3", [1127]),
    ],
)
def test_equivalence_surcharge_pairs(rate, surcharge_rate, expected):
    line = taxed(
        rate=Decimal(rate),
        tax=Decimal(rate),
        surcharge_rate=Decimal(surcharge_rate),
        surcharge=Decimal(surcharge_rate),
    )
    assert codes(line) == expected


@pytest.mark.parametrize(
    ("rate", "surcharge_rate", "operation_date", "expected"),
    [
        ("0", "0", date(2024, 6, 1), []),
        ("0", "0.5", date(2024, 6, 1), [1277]),
        ("0", "0.26", date(2024, 11, 15), [1277]),
        ("0", "0", date(2024, 11, 15), [1165]),
        ("5", "0.62", date(2024, 6, 1), []),
        ("5", "0.5", date(2024, 6, 1), [1167]),
        ("5", "0.62", date(2022, 10, 1), [1168]),
        ("5", "1.4", date(2024, 6, 1), [1160]),
        ("2", "0.26", date(2024, 11, 15), []),
        ("7.5", "1", date(2024, 11, 15), []),
    ],
)
def test_transitional_surcharges(rate, surcharge_rate, operation_date, expected):
    line = taxed(
        rate=Decimal(rate),
        tax=Decimal(rate),
        surcharge_rate=Decimal(surcharge_rate),
        surcharge=Decimal(surcharge_rate),
    )
    assert codes(line, operation_date=operation_date) == expected


def test_surcharge_needs_both_fields_and_s1():
    assert codes(taxed(surcharge_rate=Decimal("5.2"))) == [1284]
    reverse_charge = taxed(qualification=S2, rate=Decimal(0), tax=Decimal(0))
    surcharged = replace(reverse_charge, surcharge_rate=Decimal("5.2"), surcharge=Decimal("5.2"))
    assert codes(surcharged) == [1281]
