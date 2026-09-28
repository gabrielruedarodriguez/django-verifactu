from enum import StrEnum


class InvoiceType(StrEnum):
    F1 = "F1"
    F2 = "F2"
    F3 = "F3"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"


class CorrectionType(StrEnum):
    SUBSTITUTION = "S"
    DIFFERENCES = "I"


class TaxType(StrEnum):
    VAT = "01"
    IPSI = "02"
    IGIC = "03"
    OTHER = "05"


class RegimeKey(StrEnum):
    GENERAL = "01"
    EXPORT = "02"
    USED_GOODS = "03"
    INVESTMENT_GOLD = "04"
    TRAVEL_AGENCIES = "05"
    ENTITY_GROUP = "06"
    CASH_ACCOUNTING = "07"
    OTHER_INDIRECT_TAX = "08"
    TRAVEL_AGENCY_MEDIATION = "09"
    THIRD_PARTY_COLLECTIONS = "10"
    BUSINESS_PREMISES_RENTAL = "11"
    PUBLIC_WORKS_PENDING_TAX = "14"
    SUCCESSIVE_SUPPLY_PENDING_TAX = "15"
    ONE_STOP_SHOP = "17"
    EQUIVALENCE_SURCHARGE = "18"
    AGRICULTURE = "19"
    SIMPLIFIED = "20"
    # Codes 17-21 mean something else under IGIC and IPSI: these aliases share the value.
    IGIC_RETAIL_TRADER = "17"
    IGIC_SMALL_BUSINESS = "18"
    IGIC_EXEMPT_INTERIOR = "19"
    IGIC_IPSI_OPERATIONS = "20"
    IGIC_SIMPLIFIED = "21"
    IPSI_CEUTA_ARTICLE_73 = "18"
    IPSI_EXEMPT_INTERIOR = "19"
    IPSI_OBJECTIVE_ESTIMATE = "20"


class OperationQualification(StrEnum):
    S1 = "S1"
    S2 = "S2"
    N1 = "N1"
    N2 = "N2"


class ExemptionCause(StrEnum):
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"
    E4 = "E4"
    E5 = "E5"
    E6 = "E6"
    E7 = "E7"
    E8 = "E8"


class IdType(StrEnum):
    VAT_NUMBER = "02"
    PASSPORT = "03"
    OFFICIAL_ID = "04"
    RESIDENCE_CERTIFICATE = "05"
    OTHER_DOCUMENT = "06"
    NOT_REGISTERED = "07"


class IssuedBy(StrEnum):
    RECIPIENT = "D"
    THIRD_PARTY = "T"


class GeneratedBy(StrEnum):
    ISSUER = "E"
    RECIPIENT = "D"
    THIRD_PARTY = "T"


class StoredStatus(StrEnum):
    ACCEPTED = "Correcto"
    ACCEPTED_WITH_ERRORS = "AceptadoConErrores"
    CANCELLED = "Anulado"


class PreviousRejection(StrEnum):
    NO = "N"
    YES = "S"
    NOT_AT_AEAT = "X"


class SubmissionStatus(StrEnum):
    ACCEPTED = "Correcto"
    PARTIALLY_ACCEPTED = "ParcialmenteCorrecto"
    REJECTED = "Incorrecto"


class RecordStatus(StrEnum):
    ACCEPTED = "Correcto"
    ACCEPTED_WITH_ERRORS = "AceptadoConErrores"
    REJECTED = "Incorrecto"


class DuplicateStatus(StrEnum):
    VALID = "Correcta"
    ACCEPTED_WITH_ERRORS = "AceptadaConErrores"
    CANCELLED = "Anulada"


class Operation(StrEnum):
    REGISTRATION = "Alta"
    CANCELLATION = "Anulacion"
