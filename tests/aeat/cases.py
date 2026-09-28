from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from django_verifactu.aeat.codes import (
    CorrectionType,
    ExemptionCause,
    GeneratedBy,
    IdType,
    InvoiceType,
    IssuedBy,
    OperationQualification,
    PreviousRejection,
    RecordStatus,
    RegimeKey,
    TaxType,
)
from django_verifactu.aeat.domain import (
    Cancellation,
    CorrectedAmounts,
    ForeignId,
    InvoiceId,
    Party,
    PreviousRecord,
    TaxLine,
)


def vat(rate: str, base: str, tax: str) -> tuple[TaxLine, ...]:
    return (TaxLine(rate=Decimal(rate), base=Decimal(base), tax=Decimal(tax)),)


def foreign(id_type: IdType, number: str, country: str | None = None) -> tuple[Party, ...]:
    return (Party("Cliente extranjero", foreign_id=ForeignId(id_type, number, country)),)


def kind(invoice_type: InvoiceType, **changes):
    simplified = invoice_type in (InvoiceType.F2, InvoiceType.R5)
    corrective = invoice_type.value.startswith("R")
    shape = {"invoice_type": invoice_type}
    if simplified:
        shape["recipients"] = ()
    if corrective:
        shape["correction_type"] = CorrectionType.DIFFERENCES
    return lambda invoice: replace(invoice, **(shape | changes))


def invoice_type_cases(today: date, owner: Party):
    original = InvoiceId(owner.tax_id, "CONF-ORIGINAL-1", today)
    substitution = {
        "correction_type": CorrectionType.SUBSTITUTION,
        "corrected_amounts": CorrectedAmounts(base=Decimal("100"), tax=Decimal("21")),
    }
    vat_recipient = foreign(IdType.VAT_NUMBER, "IE6388047V")
    passport = foreign(IdType.PASSPORT, "AB123456", "FR")
    big = (TaxLine(base=Decimal("100000000"), rate=Decimal("21"), tax=Decimal("21000000")),)
    return {
        "F2 simplified invoice": kind(InvoiceType.F2),
        "F2 with a recipient": kind(InvoiceType.F2, recipients=(owner,)),
        "F2 at the 3010 limit": kind(InvoiceType.F2, lines=vat("21", "2487.60", "522.40")),
        "F2 over 3000": kind(InvoiceType.F2, lines=vat("21", "2487.61", "522.40")),
        "F2 over 3000 without recipient (art. 61d)": kind(
            InvoiceType.F2, lines=vat("21", "5000", "1050"), without_recipient_art_61d=True
        ),
        "F3 replacing a simplified invoice": kind(InvoiceType.F3, replaced_invoices=(original,)),
        "F1 listing replaced invoices": kind(InvoiceType.F1, replaced_invoices=(original,)),
        "R1 by differences": kind(InvoiceType.R1, corrected_invoices=(original,)),
        "R1 by substitution": kind(InvoiceType.R1, corrected_invoices=(original,), **substitution),
        "R1 without correction type": kind(InvoiceType.R1, correction_type=None),
        "F1 with a correction type": kind(
            InvoiceType.F1, correction_type=CorrectionType.DIFFERENCES
        ),
        "F1 listing corrected invoices": kind(InvoiceType.F1, corrected_invoices=(original,)),
        "R1 substitution without amounts": kind(
            InvoiceType.R1, correction_type=CorrectionType.SUBSTITUTION
        ),
        "R1 differences with amounts": kind(
            InvoiceType.R1, corrected_amounts=substitution["corrected_amounts"]
        ),
        "R2 with an EU VAT recipient": kind(InvoiceType.R2, recipients=vat_recipient),
        "R2 with a passport recipient": kind(InvoiceType.R2, recipients=passport),
        "R3 with a passport recipient": kind(InvoiceType.R3, recipients=passport),
        "R2 with an official id recipient": kind(
            InvoiceType.R2, recipients=foreign(IdType.OFFICIAL_ID, "ID123456", "FR")
        ),
        "R2 with another document recipient": kind(
            InvoiceType.R2, recipients=foreign(IdType.OTHER_DOCUMENT, "DOC123456", "FR")
        ),
        "R3 with an official id recipient": kind(
            InvoiceType.R3, recipients=foreign(IdType.OFFICIAL_ID, "ID123456", "FR")
        ),
        "R3 with a residence certificate recipient": kind(
            InvoiceType.R3, recipients=foreign(IdType.RESIDENCE_CERTIFICATE, "RC123456", "FR")
        ),
        "R3 with a NIF recipient": kind(InvoiceType.R3),
        "R4 by differences": kind(InvoiceType.R4),
        "R5 simplified correction": kind(InvoiceType.R5),
        "R5 with a recipient": kind(InvoiceType.R5, recipients=(owner,)),
        "R2 with an unchecked tax": kind(InvoiceType.R2, lines=vat("21", "100", "40")),
        "R1 differences with an unchecked tax": kind(InvoiceType.R1, lines=vat("21", "100", "40")),
        "R1 substitution with a wrong tax": kind(
            InvoiceType.R1, lines=vat("21", "100", "40"), **substitution
        ),
        "coupon on R1": kind(InvoiceType.R1, coupon=True),
        "coupon on F1": kind(InvoiceType.F1, coupon=True),
        "art. 72/73 on F1": kind(InvoiceType.F1, simplified_art_72_73=True),
        "art. 72/73 on F2": kind(InvoiceType.F2, simplified_art_72_73=True),
        "art. 61d on F1": kind(InvoiceType.F1, without_recipient_art_61d=True),
        "total over 100 million (Macrodato)": kind(InvoiceType.F1, lines=big),
        "external reference": kind(InvoiceType.F1, external_reference="PEDIDO-2026-7"),
    }


def line(**fields):
    fields = {"base": Decimal(100), "rate": Decimal(21), "tax": Decimal(21)} | fields
    return lambda invoice: replace(invoice, lines=(TaxLine(**fields),))


def surcharged(rate: str, surcharge_rate: str, **fields):
    amounts = {"rate": Decimal(rate), "tax": Decimal(rate)}
    surcharge = {"surcharge_rate": Decimal(surcharge_rate), "surcharge": Decimal(surcharge_rate)}
    return line(**(amounts | surcharge | fields))


def on(operation_date: date, change):
    return lambda invoice: replace(change(invoice), operation_date=operation_date)


def untaxed(**fields):
    return line(**({"rate": None, "tax": None, "qualification": None} | fields))


def breakdown_cases(today: date):
    s2 = {"qualification": OperationQualification.S2, "rate": Decimal(0), "tax": Decimal(0)}
    n1, n2 = OperationQualification.N1, OperationQualification.N2
    e = ExemptionCause
    public_body = (Party("Agencia Tributaria", tax_id="Q2826000H"),)
    public_works = line(regime=RegimeKey.PUBLIC_WORKS_PENDING_TAX)

    def with_recipients(change, recipients, **invoice_changes):
        return lambda i: replace(change(i), recipients=recipients, **invoice_changes)

    return {
        "exempt E1": untaxed(exemption=e.E1),
        "exempt line with rate and tax": line(qualification=None, exemption=e.E1),
        "E7 with VAT": untaxed(exemption=e.E7),
        "E7 with IGIC": untaxed(exemption=e.E7, tax_type=TaxType.IGIC),
        "E2 in the general regime": untaxed(exemption=e.E2),
        "E2 as an export": untaxed(exemption=e.E2, regime=RegimeKey.EXPORT),
        "E5 to a NIF recipient": untaxed(exemption=e.E5),
        "E5 to a foreign recipient": with_recipients(
            untaxed(exemption=e.E5), foreign(IdType.PASSPORT, "AB123456", "FR")
        ),
        "reverse charge S2": line(**s2),
        "S2 charging tax": line(qualification=OperationQualification.S2),
        "S2 on F2": lambda i: replace(line(**s2)(i), invoice_type=InvoiceType.F2, recipients=()),
        "not subject N1 with VAT": untaxed(qualification=n1),
        "N1 with VAT and a rate": untaxed(qualification=n1, rate=Decimal(21), tax=Decimal(0)),
        "N1 with IGIC and a rate": untaxed(
            qualification=n1, rate=Decimal(7), tax=Decimal(0), tax_type=TaxType.IGIC
        ),
        "N2 with IGIC charging tax": untaxed(
            qualification=n2, tax=Decimal(5), tax_type=TaxType.IGIC
        ),
        "S1 without rate": line(rate=None),
        "VAT line without regime": line(regime=None),
        "IGIC line without regime": line(tax_type=TaxType.IGIC, regime=None),
        "IPSI line without regime": line(tax_type=TaxType.IPSI, regime=None),
        "other tax with a regime": line(tax_type=TaxType.OTHER),
        "other tax without regime": line(tax_type=TaxType.OTHER, regime=None),
        "VAT with IGIC regime 21": line(regime=RegimeKey.IGIC_SIMPLIFIED),
        "IGIC with regime 21": line(tax_type=TaxType.IGIC, regime=RegimeKey.IGIC_SIMPLIFIED),
        "IPSI general regime": line(tax_type=TaxType.IPSI),
        "IPSI with cash accounting": line(tax_type=TaxType.IPSI, regime=RegimeKey.CASH_ACCOUNTING),
        "export charging VAT": line(regime=RegimeKey.EXPORT),
        "used goods N1": untaxed(regime=RegimeKey.USED_GOODS, qualification=n1),
        "used goods exempt": untaxed(regime=RegimeKey.USED_GOODS, exemption=e.E1),
        "investment gold S1": line(regime=RegimeKey.INVESTMENT_GOLD),
        "investment gold S2": line(regime=RegimeKey.INVESTMENT_GOLD, **s2),
        "entity group without base at cost": line(regime=RegimeKey.ENTITY_GROUP),
        "entity group with base at cost": line(
            regime=RegimeKey.ENTITY_GROUP, base_at_cost=Decimal(100)
        ),
        "cash accounting S2": line(regime=RegimeKey.CASH_ACCOUNTING, **s2),
        "regime 08 charging VAT": line(regime=RegimeKey.OTHER_INDIRECT_TAX),
        "regime 08 N2": untaxed(regime=RegimeKey.OTHER_INDIRECT_TAX, qualification=n2),
        "third party collections N1": untaxed(
            regime=RegimeKey.THIRD_PARTY_COLLECTIONS, qualification=n1
        ),
        "third party collections S1": line(regime=RegimeKey.THIRD_PARTY_COLLECTIONS),
        "business premises rental at 10": line(
            regime=RegimeKey.BUSINESS_PREMISES_RENTAL, rate=Decimal(10), tax=Decimal(10)
        ),
        "public works without operation date": with_recipients(public_works, public_body),
        "public works to a public body": with_recipients(
            public_works, public_body, operation_date=today + timedelta(days=30)
        ),
        "public works to a company": lambda i: replace(
            public_works(i), operation_date=today + timedelta(days=30)
        ),
        "IGIC regime 20 charging tax": line(
            tax_type=TaxType.IGIC, regime=RegimeKey.IGIC_IPSI_OPERATIONS
        ),
        "base at cost with VAT": line(base_at_cost=Decimal(100)),
        "base at cost with IPSI": line(base_at_cost=Decimal(100), tax_type=TaxType.IPSI),
        "IGIC at 7": line(tax_type=TaxType.IGIC, rate=Decimal(7), tax=Decimal(7)),
        "surcharge 5.2 on 21": surcharged("21", "5.2"),
        "surcharge 1.4 on 21": surcharged("21", "1.4"),
        "surcharge 1.4 on 10": surcharged("10", "1.4"),
        "surcharge 0.5 on 4": surcharged("4", "0.5"),
        "surcharge 0 on 0": surcharged("0", "0"),
        "surcharge 0.26 on 0": surcharged("0", "0.26"),
        "surcharge 0.5 on 0": surcharged("0", "0.5"),
        "surcharge 0 on 0 in mid 2024": on(date(2024, 6, 1), surcharged("0", "0")),
        "surcharge 0.5 on 0 in mid 2024": on(date(2024, 6, 1), surcharged("0", "0.5")),
        "surcharge 0.26 on 0 in late 2024": on(date(2024, 11, 15), surcharged("0", "0.26")),
        "surcharge 0 on 0 in late 2024": on(date(2024, 11, 15), surcharged("0", "0")),
        "surcharge 0.62 on 5 in mid 2024": on(date(2024, 6, 1), surcharged("5", "0.62")),
        "surcharge 0.5 on 5 in mid 2024": on(date(2024, 6, 1), surcharged("5", "0.5")),
        "surcharge 0.62 on 5 in late 2022": on(date(2022, 10, 1), surcharged("5", "0.62")),
        "surcharge 1.4 on 5 in mid 2024": on(date(2024, 6, 1), surcharged("5", "1.4")),
        "surcharge 0.26 on 2 in late 2024": on(date(2024, 11, 15), surcharged("2", "0.26")),
        "surcharge 0.5 on 2 in late 2024": on(date(2024, 11, 15), surcharged("2", "0.5")),
        "surcharge 1 on 7.5 in late 2024": on(date(2024, 11, 15), surcharged("7.5", "1")),
        "surcharge 0.5 on 7.5 in late 2024": on(date(2024, 11, 15), surcharged("7.5", "0.5")),
        "surcharge rate 3": surcharged("21", "3"),
        "surcharge rate without amount": line(surcharge_rate=Decimal("5.2")),
        "surcharge on reverse charge": surcharged("0", "5.2", qualification=s2["qualification"]),
    }


def change(**fields):
    return lambda invoice: replace(invoice, **fields)


def third_party_cases(owner: Party):
    public_body = Party("Agencia Tributaria", tax_id="Q2826000H")
    by_third_party = {"issued_by": IssuedBy.THIRD_PARTY}
    not_registered = Party("Gestor", foreign_id=ForeignId(IdType.NOT_REGISTERED, "12345678Z", "ES"))
    official_id = Party("Gestor", foreign_id=ForeignId(IdType.OFFICIAL_ID, "ID123456", "ES"))
    vat_number = Party("Google Ireland", foreign_id=ForeignId(IdType.VAT_NUMBER, "IE6388047V"))
    return {
        "issued by a third party": change(third_party=public_body, **by_third_party),
        "third party without issued_by": change(third_party=public_body),
        "third party on an invoice issued by the recipient": change(
            issued_by=IssuedBy.RECIPIENT, third_party=public_body
        ),
        "issued by a third party without third party": change(**by_third_party),
        "issued by the recipient": change(issued_by=IssuedBy.RECIPIENT),
        "issued by the recipient without recipients": kind(
            InvoiceType.F2, issued_by=IssuedBy.RECIPIENT
        ),
        "third party is the issuer": change(third_party=owner, **by_third_party),
        "third party NIF with a wrong letter": change(
            third_party=Party("Gestor", tax_id="89890002A"), **by_third_party
        ),
        "third party not registered": change(third_party=not_registered, **by_third_party),
        "third party with a Spanish official id": change(
            third_party=official_id, **by_third_party
        ),
        "third party with an EU VAT number": change(third_party=vat_number, **by_third_party),
        "billing agreement that does not exist": change(billing_agreement="AC-TEST-1"),
        "system agreement that does not exist": change(system_agreement="SIS-TEST-1"),
    }


def cancellation_cases(owner: Party):
    public_body = Party("Agencia Tributaria", tax_id="Q2826000H")
    french = Party("Cliente extranjero", foreign_id=ForeignId(IdType.PASSPORT, "AB123456", "FR"))

    def spanish(id_type: IdType):
        return Party("Cliente", foreign_id=ForeignId(id_type, "12345678Z", "ES"))

    def by(generated_by: GeneratedBy, generator: Party | None):
        return lambda c: replace(c, generated_by=generated_by, generator=generator)

    def number_with(suffix: str):
        return lambda c: replace(
            c, invoice_number=c.invoice_number + suffix, without_previous_record=True
        )

    return {
        "plain cancellation": lambda c: c,
        "cancellation with an external reference": lambda c: replace(c, external_reference="ERP-1"),
        "cancelled invoice number with =": number_with("="),
        "cancelled invoice number with ñ": number_with("ñ"),
        "cancelled by the recipient": by(GeneratedBy.RECIPIENT, public_body),
        "cancelled by a foreign recipient": by(GeneratedBy.RECIPIENT, french),
        "cancelled by a third party": by(GeneratedBy.THIRD_PARTY, public_body),
        "cancelled by the issuer itself": by(GeneratedBy.ISSUER, owner),
        "cancelled by the issuer without NIF": by(GeneratedBy.ISSUER, french),
        "generated_by without generator": by(GeneratedBy.RECIPIENT, None),
        "third party generator not registered": by(
            GeneratedBy.THIRD_PARTY, spanish(IdType.NOT_REGISTERED)
        ),
        "recipient generator with a Spanish official id": by(
            GeneratedBy.RECIPIENT, spanish(IdType.OFFICIAL_ID)
        ),
        "third party generator with a Spanish official id": by(
            GeneratedBy.THIRD_PARTY, spanish(IdType.OFFICIAL_ID)
        ),
    }


def business_cases(today: date, owner: Party):
    cases = invoice_type_cases(today, owner) | breakdown_cases(today) | third_party_cases(owner)
    return cases | {
        "valid": lambda i: i,
        "invoice number with <": lambda i: replace(i, invoice_number=i.invoice_number + "<"),
        "invoice number with ñ": lambda i: replace(i, invoice_number=i.invoice_number + "ñ"),
        "issue date tomorrow": lambda i: replace(i, issue_date=today + timedelta(days=1)),
        "issue date before 28-10-2024": lambda i: replace(i, issue_date=date(2024, 10, 27)),
        "issue date in 2023": lambda i: replace(i, issue_date=date(2023, 12, 31)),
        "issue date on 2024-01-01": lambda i: replace(i, issue_date=date(2024, 1, 1)),
        "record not at the AEAT without amendment": lambda i: replace(
            i, previous_rejection=PreviousRejection.NOT_AT_AEAT
        ),
        "previous rejection without amendment": lambda i: replace(
            i, previous_rejection=PreviousRejection.YES
        ),
        "VAT rate 3": lambda i: replace(i, lines=vat("3", "100", "3")),
        "VAT rate 5 out of its window": lambda i: replace(i, lines=vat("5", "100", "5")),
        "VAT rate 2 out of its window": lambda i: replace(i, lines=vat("2", "100", "2")),
        "VAT rate 7.5 out of its window": lambda i: replace(i, lines=vat("7.5", "100", "7.5")),
        "tax off by more than 10": lambda i: replace(i, lines=vat("21", "100", "31.01")),
        "tax and base with different sign": lambda i: replace(i, lines=vat("21", "-10", "2.10")),
        "recipient NIF numbered zero": lambda i: replace(
            i, recipients=(Party("Cliente", tax_id="00000000T"),)
        ),
        "recipient NIF with a wrong letter": lambda i: replace(
            i, recipients=(Party("Cliente", tax_id="89890002A"),)
        ),
        "passport from France": lambda i: replace(
            i, recipients=foreign(IdType.PASSPORT, "AB123456", "FR")
        ),
        "passport without country": lambda i: replace(
            i, recipients=foreign(IdType.PASSPORT, "AB123456")
        ),
        "EU VAT number registered in VIES": lambda i: replace(
            i, recipients=foreign(IdType.VAT_NUMBER, "IE6388047V")
        ),
        "EU VAT number not in VIES": lambda i: replace(
            i, recipients=foreign(IdType.VAT_NUMBER, "DE123456789")
        ),
        "VAT number with another country": lambda i: replace(
            i, recipients=foreign(IdType.VAT_NUMBER, "DE123456789", "FR")
        ),
        "VAT number with a wrong structure": lambda i: replace(
            i, recipients=foreign(IdType.VAT_NUMBER, "DE12345")
        ),
        "GB VAT number after Brexit": lambda i: replace(
            i, recipients=foreign(IdType.VAT_NUMBER, "GB123456789")
        ),
        "XI VAT number before Brexit": lambda i: replace(
            i,
            recipients=foreign(IdType.VAT_NUMBER, "XI123456789"),
            operation_date=date(2020, 12, 1),
        ),
        "official id with country ES": lambda i: replace(
            i, recipients=foreign(IdType.OFFICIAL_ID, "123", "ES")
        ),
        "not registered outside Spain": lambda i: replace(
            i, recipients=foreign(IdType.NOT_REGISTERED, "12345678Z", "FR")
        ),
        "not registered in Spain": lambda i: replace(
            i, recipients=foreign(IdType.NOT_REGISTERED, "12345678Z", "ES")
        ),
        "not registered with a company NIF": lambda i: replace(
            i, recipients=foreign(IdType.NOT_REGISTERED, "B12345674", "ES")
        ),
        "operation date 21 years ago": lambda i: replace(
            i, operation_date=date(today.year - 21, 1, 1)
        ),
        "operation date next week": lambda i: replace(
            i, operation_date=today + timedelta(days=7)
        ),
        "operation date in two years": lambda i: replace(
            i, operation_date=date(today.year + 2, 1, 1)
        ),
        "operation date before the issue date": lambda i: replace(
            i, operation_date=today - timedelta(days=10)
        ),
        "two recipients": lambda i: replace(
            i, recipients=(owner, *foreign(IdType.PASSPORT, "AB123456", "FR"))
        ),
    }


ACCEPTED = (RecordStatus.ACCEPTED, None)
DUPLICATED = (RecordStatus.REJECTED, 3000)
NOT_FOUND = (RecordStatus.REJECTED, 3002)
REJECTED = (RecordStatus.REJECTED, 1124)
WITH_ERRORS = (RecordStatus.ACCEPTED_WITH_ERRORS, 2001)


def register(**changes):
    return lambda invoice: replace(invoice, **changes)


def cancel(**changes):
    return lambda invoice: Cancellation(
        invoice.issuer_tax_id, invoice.invoice_number, invoice.issue_date, **changes
    )


# The official tables of admissible operations (Validaciones, annex 6): each case is a
# sequence of records for one invoice, with the answer the AEAT must give to each one.
def lifecycle_cases():
    amend = register(amendment=True)
    not_at_aeat = register(amendment=True, previous_rejection=PreviousRejection.NOT_AT_AEAT)
    rejected = {"lines": vat("3", "100", "3")}
    unregistered = foreign(IdType.NOT_REGISTERED, "12345678Z", "ES")
    without_record = cancel(without_previous_record=True)
    return {
        "alta": [(register(), ACCEPTED)],
        "alta of a registered invoice": [(register(), ACCEPTED), (register(), DUPLICATED)],
        "alta of a cancelled invoice": [
            (register(), ACCEPTED),
            (cancel(), ACCEPTED),
            (register(), DUPLICATED),
        ],
        "alta after a rejection": [(register(**rejected), REJECTED), (not_at_aeat, ACCEPTED)],
        "plain alta after a rejection": [(register(**rejected), REJECTED), (register(), ACCEPTED)],
        "amendment": [(register(), ACCEPTED), (amend, ACCEPTED)],
        "amendment of an unknown invoice": [(amend, NOT_FOUND)],
        "amendment of a cancelled invoice reactivates it": [
            (register(), ACCEPTED),
            (cancel(), ACCEPTED),
            (amend, ACCEPTED),
        ],
        "amendment of an accepted with errors": [
            (register(recipients=unregistered), WITH_ERRORS),
            (amend, ACCEPTED),
        ],
        "alta of an accepted with errors": [
            (register(recipients=unregistered), WITH_ERRORS),
            (register(), DUPLICATED),
        ],
        "amendment after a rejected amendment": [
            (register(), ACCEPTED),
            (register(amendment=True, **rejected), REJECTED),
            (register(amendment=True, previous_rejection=PreviousRejection.YES), ACCEPTED),
        ],
        "amendment after a rejection of an unknown invoice": [
            (register(amendment=True, previous_rejection=PreviousRejection.YES), NOT_FOUND),
        ],
        "amendment with explicit no rejection": [
            (register(), ACCEPTED),
            (register(amendment=True, previous_rejection=PreviousRejection.NO), ACCEPTED),
        ],
        "amendment of a record not at the AEAT": [(not_at_aeat, ACCEPTED)],
        "amendment not at the AEAT of a registered invoice": [
            (register(), ACCEPTED),
            (not_at_aeat, DUPLICATED),
        ],
        "amendment not at the AEAT of a cancelled invoice": [
            (register(), ACCEPTED),
            (cancel(), ACCEPTED),
            (not_at_aeat, DUPLICATED),
        ],
        "cancellation": [(register(), ACCEPTED), (cancel(), ACCEPTED)],
        "cancellation of an unknown invoice": [(cancel(), NOT_FOUND)],
        "cancellation of a cancelled invoice": [
            (register(), ACCEPTED),
            (cancel(), ACCEPTED),
            (cancel(), ACCEPTED),
        ],
        "cancellation after a rejection": [
            (register(), ACCEPTED),
            (cancel(previous_rejection=True), ACCEPTED),
        ],
        "cancellation after a rejection of an unknown invoice": [
            (cancel(previous_rejection=True), NOT_FOUND),
        ],
        "cancellation without previous record": [(without_record, ACCEPTED)],
        "cancellation without previous record of a registered invoice": [
            (register(), ACCEPTED),
            (without_record, DUPLICATED),
        ],
        "cancellation without previous record of a cancelled invoice": [
            (without_record, ACCEPTED),
            (without_record, DUPLICATED),
        ],
        "cancellation without previous record after a rejection": [
            (cancel(without_previous_record=True, previous_rejection=True), ACCEPTED),
        ],
    }


def chain_cases(previous: PreviousRecord):
    return {
        "previous fingerprint in lowercase": replace(
            previous, fingerprint=previous.fingerprint.lower()
        ),
        "previous fingerprint of 63 characters": replace(
            previous, fingerprint=previous.fingerprint[:63]
        ),
        "previous fingerprint not hexadecimal": replace(previous, fingerprint="G" * 64),
        "previous issuer with a wrong NIF letter": replace(previous, issuer_tax_id="89890001A"),
        "previous issuer is another taxpayer": replace(previous, issuer_tax_id="Q2826000H"),
        "previous record unknown to the AEAT": replace(previous, invoice_number="UNKNOWN-1"),
        "previous fingerprint that does not match": replace(previous, fingerprint="A" * 64),
    }


def software_cases():
    def producer(party: Party):
        return lambda software: replace(software, producer=party)

    def foreign_producer(id_type: IdType, number: str, country: str | None = None):
        return producer(Party("Software House", foreign_id=ForeignId(id_type, number, country)))

    return {
        "producer NIF with a wrong letter": producer(Party("Productor", tax_id="89890001A")),
        "producer NIF not in the census": producer(Party("Productor", tax_id="12345678Z")),
        "producer NIF numbered zero": producer(Party("Productor", tax_id="00000000T")),
        "producer is a public body": producer(Party("Agencia Tributaria", tax_id="Q2826000H")),
        "producer with an EU VAT number": foreign_producer(IdType.VAT_NUMBER, "IE6388047V"),
        "producer VAT number not in VIES": foreign_producer(IdType.VAT_NUMBER, "DE123456789"),
        "producer VAT number with a wrong structure": foreign_producer(
            IdType.VAT_NUMBER, "DE12345"
        ),
        "producer VAT number with another country": foreign_producer(
            IdType.VAT_NUMBER, "IE6388047V", "FR"
        ),
        "producer GB VAT number after Brexit": foreign_producer(IdType.VAT_NUMBER, "GB123456789"),
        "producer passport from Spain": foreign_producer(IdType.PASSPORT, "AB123456", "ES"),
        "producer passport from France": foreign_producer(IdType.PASSPORT, "AB123456", "FR"),
        "producer official id from Spain": foreign_producer(IdType.OFFICIAL_ID, "X1234567", "ES"),
        "producer not registered": foreign_producer(IdType.NOT_REGISTERED, "12345678Z", "ES"),
        "producer official id without country": foreign_producer(IdType.OFFICIAL_ID, "X1"),
        "producer with another document": foreign_producer(
            IdType.OTHER_DOCUMENT, "EIN-12-3456789", "US"
        ),
        "system id of one character": lambda software: replace(software, system_id="A"),
        "system id in lowercase": lambda software: replace(software, system_id="fa"),
        "system id with Ñ": lambda software: replace(software, system_id="Ñ1"),
        "system id with digits": lambda software: replace(software, system_id="09"),
        "multiple taxpayers without the possibility": lambda software: replace(
            software, multiple_taxpayers_possible=False, multiple_taxpayers=True
        ),
    }


def header_cases(taxpayer: Party, today: date):
    agent = Party("Asesoria", tax_id="Q2826000H")
    return {
        "taxpayer NIF with a wrong letter": {"taxpayer_tax_id": "89890001A"},
        "taxpayer NIF of 8 characters": {"taxpayer_tax_id": taxpayer.tax_id[:8]},
        "blank taxpayer name": {"taxpayer_name": " "},
        "taxpayer name over 120 characters": {"taxpayer_name": "x" * 121},
        "taxpayer name not in the census": {"taxpayer_name": "Nombre Inventado SL"},
        "representative is the taxpayer": {"representative": taxpayer},
        "representative with a wrong NIF letter": {
            "representative": replace(agent, tax_id="89890002A")
        },
        "representative NIF of 8 characters": {"representative": replace(agent, tax_id="Q2826000")},
        "representative name not in the census": {
            "representative": replace(agent, name="Nombre Inventado SL")
        },
        "blank representative name": {"representative": replace(agent, name=" ")},
        "representative name over 120 characters": {
            "representative": replace(agent, name="x" * 121)
        },
        "technical incident": {"incident": True},
        "VERI*FACTU ends this year": {"verifactu_end_date": date(today.year, 12, 31)},
        "VERI*FACTU ended last year": {"verifactu_end_date": date(today.year - 1, 12, 31)},
        "VERI*FACTU ends mid-year": {"verifactu_end_date": date(today.year, 6, 30)},
        "VERI*FACTU ends next year": {"verifactu_end_date": date(today.year + 1, 12, 31)},
        "no records": {"records": 0},
        "1001 records": {"records": 1001},
    }


def query_cases(taxpayer: Party, today: date, software):
    first_day = today.replace(day=1)
    passport = Party("Kunde", foreign_id=ForeignId(IdType.PASSPORT, "AB123456", "FR"))
    return {
        "valid query": {},
        "taxpayer NIF with a wrong letter": {"taxpayer_tax_id": "89890001A"},
        "recipient NIF with a wrong letter": {
            "taxpayer_tax_id": "89890001A",
            "as_recipient": True,
        },
        "taxpayer NIF of another taxpayer": {"taxpayer_tax_id": "Q2826000H"},
        "taxpayer NIF not in the census": {"taxpayer_tax_id": "12345678Z"},
        "blank taxpayer name": {"taxpayer_name": " "},
        "taxpayer name over 120 characters": {"taxpayer_name": "x" * 121},
        "taxpayer name not in the census": {"taxpayer_name": "Nombre Inventado SL"},
        "month 0": {"month": 0},
        "month 13": {"month": 13},
        "year without records": {"year": 999},
        "as recipient": {"as_recipient": True},
        "as representative": {"as_representative": True},
        "representative flag as recipient": {"as_recipient": True, "as_representative": True},
        "software shown to a recipient": {"as_recipient": True, "show_software": True},
        "issuer name and software shown": {"show_issuer_name": True, "show_software": True},
        "invoice number over 60 characters": {"invoice_number": "X" * 61},
        "invoice number with <": {"invoice_number": "A<1"},
        "counterparty NIF with a wrong letter": {
            "counterparty": Party("Cliente", tax_id="89890001A")
        },
        "counterparty NIF not in the census": {
            "counterparty": Party("Cliente", tax_id="12345678Z")
        },
        "counterparty with a foreign id": {"counterparty": passport},
        "counterparty with another name": {"counterparty": replace(taxpayer, name="Otro")},
        "exact issue date": {"issue_date": today},
        "open issue range": {"issued_from": first_day},
        "issue range of one day": {"issued_from": today, "issued_to": today},
        "reversed issue range": {"issued_from": today, "issued_to": today - timedelta(days=1)},
        "software filter": {"software": software},
        "external reference over 60 characters": {"external_reference": "x" * 61},
        "unknown pagination key": {"after": InvoiceId(taxpayer.tax_id, "NOPE-1", today)},
    }
