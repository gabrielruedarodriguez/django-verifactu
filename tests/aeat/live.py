import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from django_verifactu.aeat.domain import BillingSoftware, Party, QueryPage, SubmissionResult
from django_verifactu.aeat.submission import build_submission
from django_verifactu.aeat.transport import client_ssl_context, send_query, send_submission

CERTIFICATE = os.environ.get("VERIFACTU_TEST_CERTIFICATE")
PASSWORD_FILE = os.environ.get("VERIFACTU_TEST_PASSWORD_FILE")

WAIT_SECONDS = 60
_last_submission = -float(WAIT_SECONDS)

requires_aeat = pytest.mark.skipif(
    not (CERTIFICATE and PASSWORD_FILE),
    reason="set VERIFACTU_TEST_CERTIFICATE and VERIFACTU_TEST_PASSWORD_FILE to call the AEAT",
)


@dataclass(frozen=True)
class Taxpayer:
    tax_id: str
    name: str


@cache
def credentials() -> tuple[bytes, str]:
    return Path(CERTIFICATE).read_bytes(), Path(PASSWORD_FILE).read_text().strip()


def taxpayer() -> Taxpayer:
    data, password = credentials()
    subject = pkcs12.load_key_and_certificates(data, password.encode())[1].subject
    tax_id = subject.get_attributes_for_oid(NameOID.ORGANIZATION_IDENTIFIER)[0].value
    name = subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)[0].value
    return Taxpayer(tax_id.removeprefix("VATES-"), name)


def software(owner: Taxpayer, installation: str = "1") -> BillingSoftware:
    return BillingSoftware(
        producer=Party(owner.name, tax_id=owner.tax_id),
        name="django-verifactu",
        system_id="DV",
        version="0.0.1",
        installation_number=installation,
        multiple_taxpayers_possible=False,
        multiple_taxpayers=False,
    )


def now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Madrid")).replace(microsecond=0)


def submit(owner: Taxpayer, records: list) -> SubmissionResult:
    return send(
        build_submission(taxpayer_tax_id=owner.tax_id, taxpayer_name=owner.name, records=records)
    )


def send(submission) -> SubmissionResult:
    global _last_submission
    data, password = credentials()
    time.sleep(max(0.0, _last_submission + WAIT_SECONDS - time.monotonic()))
    try:
        return send_submission(
            submission,
            ssl_context=client_ssl_context(data, password),
            production=False,
            seal_certificate=False,
        )
    finally:
        _last_submission = time.monotonic()


def validation_result(url: str) -> str:
    answer = json.loads(httpx.get(url + "&formato=json", timeout=30).content.decode("iso-8859-15"))
    return answer["respuesta"]["resultado"]


def ask(query) -> QueryPage:
    data, password = credentials()
    return send_query(
        query,
        ssl_context=client_ssl_context(data, password),
        production=False,
        seal_certificate=False,
    )
