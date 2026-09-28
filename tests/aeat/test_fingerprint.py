from pathlib import Path

from lxml import etree

from django_verifactu.aeat.fingerprint import cancellation_fingerprint, registration_fingerprint

FINGERPRINT_1 = "3C464DAF61ACB827C65FDA19F352A4E3BDC2C640E9E9FC4CC058073F38F12F60"
FINGERPRINT_2 = "F7B94CFD8924EDFF273501B01EE5153E4CE8F259766F88CF6ACB8935802A2B97"

REGISTRATION_1 = {
    "issuer_tax_id": "89890001K",
    "invoice_number": "12345678/G33",
    "issue_date": "01-01-2024",
    "invoice_type": "F1",
    "total_tax": "12.35",
    "total_amount": "123.45",
    "previous_fingerprint": "",
    "generated_at": "2024-01-01T19:20:30+01:00",
}


def test_first_registration():
    assert registration_fingerprint(**REGISTRATION_1) == FINGERPRINT_1


def test_chained_registration():
    registration_2 = REGISTRATION_1 | {
        "invoice_number": "12345679/G34",
        "previous_fingerprint": FINGERPRINT_1,
        "generated_at": "2024-01-01T19:20:35+01:00",
    }
    assert registration_fingerprint(**registration_2) == FINGERPRINT_2


def test_chained_cancellation():
    assert cancellation_fingerprint(
        issuer_tax_id="89890001K",
        invoice_number="12345679/G34",
        issue_date="01-01-2024",
        previous_fingerprint=FINGERPRINT_2,
        generated_at="2024-01-01T19:20:40+01:00",
    ) == "177547C0D57AC74748561D054A9CEC14B4C4EA23D1BEFD6F2E69E3A388F90C68"


def test_official_example_matches_its_own_fingerprint():
    record = etree.parse(Path(__file__).parent / "fixtures" / "ejemploRegistro.xml").getroot()

    def value(path: str) -> str:
        return record.findtext(path, namespaces={"sf": record.nsmap["sum1"]})

    assert registration_fingerprint(
        issuer_tax_id=value("sf:IDFactura/sf:IDEmisorFactura"),
        invoice_number=value("sf:IDFactura/sf:NumSerieFactura"),
        issue_date=value("sf:IDFactura/sf:FechaExpedicionFactura"),
        invoice_type=value("sf:TipoFactura"),
        total_tax=value("sf:CuotaTotal"),
        total_amount=value("sf:ImporteTotal"),
        previous_fingerprint=value("sf:Encadenamiento/sf:RegistroAnterior/sf:Huella"),
        generated_at=value("sf:FechaHoraHusoGenRegistro"),
    ) == value("sf:Huella")


def test_trims_like_java():
    padded = REGISTRATION_1 | {"invoice_number": " 12345678/G33\t"}
    no_break_space = REGISTRATION_1 | {"invoice_number": " 12345678/G33"}
    assert registration_fingerprint(**padded) == FINGERPRINT_1
    assert registration_fingerprint(**no_break_space) != FINGERPRINT_1
