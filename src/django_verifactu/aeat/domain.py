from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django_verifactu.aeat.codes import (
    CorrectionType,
    DuplicateStatus,
    ExemptionCause,
    GeneratedBy,
    IdType,
    InvoiceType,
    IssuedBy,
    Operation,
    OperationQualification,
    PreviousRejection,
    RecordStatus,
    RegimeKey,
    StoredStatus,
    SubmissionStatus,
    TaxType,
)


@dataclass(frozen=True)
class TaxLine:
    base: Decimal
    rate: Decimal | None = None
    tax: Decimal | None = None
    tax_type: TaxType = TaxType.VAT
    regime: RegimeKey | None = RegimeKey.GENERAL
    qualification: OperationQualification | None = OperationQualification.S1
    exemption: ExemptionCause | None = None
    base_at_cost: Decimal | None = None
    surcharge_rate: Decimal | None = None
    surcharge: Decimal | None = None


@dataclass(frozen=True)
class ForeignId:
    id_type: IdType
    number: str
    country: str | None = None


@dataclass(frozen=True)
class Party:
    name: str
    tax_id: str | None = None
    foreign_id: ForeignId | None = None


@dataclass(frozen=True)
class InvoiceId:
    issuer_tax_id: str
    invoice_number: str
    issue_date: date


@dataclass(frozen=True)
class CorrectedAmounts:
    base: Decimal
    tax: Decimal


@dataclass(frozen=True)
class Invoice:
    issuer_tax_id: str
    issuer_name: str
    invoice_number: str
    issue_date: date
    description: str
    recipients: tuple[Party, ...]
    lines: tuple[TaxLine, ...]
    operation_date: date | None = None
    invoice_type: InvoiceType = InvoiceType.F1
    correction_type: CorrectionType | None = None
    corrected_invoices: tuple[InvoiceId, ...] = ()
    replaced_invoices: tuple[InvoiceId, ...] = ()
    corrected_amounts: CorrectedAmounts | None = None
    simplified_art_72_73: bool = False
    without_recipient_art_61d: bool = False
    coupon: bool = False
    external_reference: str | None = None
    issued_by: IssuedBy | None = None
    third_party: Party | None = None
    billing_agreement: str | None = None
    system_agreement: str | None = None
    amendment: bool = False
    previous_rejection: PreviousRejection | None = None


@dataclass(frozen=True)
class Cancellation:
    issuer_tax_id: str
    invoice_number: str
    issue_date: date
    external_reference: str | None = None
    without_previous_record: bool = False
    previous_rejection: bool = False
    generated_by: GeneratedBy | None = None
    generator: Party | None = None


@dataclass(frozen=True)
class BillingSoftware:
    producer: Party
    name: str
    system_id: str
    version: str
    installation_number: str
    multiple_taxpayers_possible: bool
    multiple_taxpayers: bool


@dataclass(frozen=True)
class Query:
    taxpayer_tax_id: str
    taxpayer_name: str
    year: int
    month: int
    as_recipient: bool = False
    as_representative: bool = False
    invoice_number: str | None = None
    counterparty: Party | None = None
    issue_date: date | None = None
    issued_from: date | None = None
    issued_to: date | None = None
    software: BillingSoftware | None = None
    external_reference: str | None = None
    after: InvoiceId | None = None
    show_issuer_name: bool = False
    show_software: bool = False


@dataclass(frozen=True)
class PreviousRecord:
    issuer_tax_id: str
    invoice_number: str
    issue_date: date
    fingerprint: str


# Validaciones 4.3.1: admissible errors that do not have to be amended.
NO_AMENDMENT_NEEDED = frozenset({2004, 2009})


@dataclass(frozen=True)
class DuplicateRecord:
    request_id: str
    status: DuplicateStatus
    error_code: int | None
    error_description: str | None

    @property
    def needs_amendment(self) -> bool:
        return (
            self.status is DuplicateStatus.ACCEPTED_WITH_ERRORS
            and self.error_code not in NO_AMENDMENT_NEEDED
        )


@dataclass(frozen=True)
class RecordResult:
    issuer_tax_id: str
    invoice_number: str
    issue_date: date
    operation: Operation
    external_reference: str | None
    status: RecordStatus
    error_code: int | None
    error_description: str | None
    duplicate: DuplicateRecord | None

    @property
    def needs_amendment(self) -> bool:
        # A duplicate (3000) answers for the record the AEAT already holds.
        if self.duplicate is not None:
            return self.duplicate.needs_amendment
        return (
            self.status is RecordStatus.ACCEPTED_WITH_ERRORS
            and self.error_code not in NO_AMENDMENT_NEEDED
        )


@dataclass(frozen=True)
class SubmissionResult:
    status: SubmissionStatus
    csv: str | None
    wait_seconds: int
    presented_at: datetime | None
    presenter_tax_id: str | None
    records: tuple[RecordResult, ...]


@dataclass(frozen=True)
class StoredRecord:
    invoice: InvoiceId
    status: StoredStatus
    error_code: int | None
    error_description: str | None
    modified_at: datetime
    invoice_type: InvoiceType | None
    description: str | None
    total_tax: Decimal | None
    total_amount: Decimal | None
    external_reference: str | None
    issuer_name: str | None
    software: BillingSoftware | None
    generated_at: datetime | None
    fingerprint: str | None
    presented_at: datetime | None
    presenter_tax_id: str | None
    request_id: str | None

    @property
    def needs_amendment(self) -> bool:
        return (
            self.status is StoredStatus.ACCEPTED_WITH_ERRORS
            and self.error_code not in NO_AMENDMENT_NEEDED
        )


@dataclass(frozen=True)
class QueryPage:
    records: tuple[StoredRecord, ...]
    next_page: InvoiceId | None
