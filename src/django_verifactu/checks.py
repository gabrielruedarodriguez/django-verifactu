from collections.abc import Mapping
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfoNotFoundError

from cryptography.hazmat.primitives.serialization import pkcs12
from django.conf import settings
from django.core.checks import CheckMessage, Error, Warning, register
from django.utils.module_loading import import_string

from django_verifactu import conf
from django_verifactu.aeat.domain import Party
from django_verifactu.aeat.submission import validate_header
from django_verifactu.aeat.transport import client_ssl_context
from django_verifactu.aeat.validation import validate_software

# XSD limits the AEAT enforces (1100) on SistemaInformatico values.
_LIMITS = {"name": 30, "system_id": 2, "version": 50}


@register()
def check_settings(app_configs, **kwargs) -> list[Error]:
    errors = []
    if not settings.USE_TZ:
        errors.append(Error("django_verifactu needs USE_TZ = True", id="django_verifactu.E001"))
    try:
        production = conf.production()
    except (AttributeError, KeyError, TypeError):
        production = None
    if not isinstance(production, bool):
        message = "set VERIFACTU['PRODUCTION'] to True or False"
        errors.append(Error(message, id="django_verifactu.E002"))
    try:
        software = conf.software("1", False)
        conf.time_zone()
    except (AttributeError, KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as error:
        message = f"VERIFACTU['SOFTWARE'] or ['TIME_ZONE'] is invalid: {error!r}"
        return [*errors, Error(message, id="django_verifactu.E003")]
    texts = all(isinstance(getattr(software, field), str) for field in _LIMITS)
    if not isinstance(software.producer, Party) or not texts:
        message = "VERIFACTU['SOFTWARE'] needs a Party producer and text name, system_id, version"
        return [*errors, Error(message, id="django_verifactu.E003")]
    for field, limit in _LIMITS.items():
        value = getattr(software, field)
        if not value.strip() or len(value) > limit:
            message = f"VERIFACTU['SOFTWARE']['{field}'] must have 1 to {limit} characters"
            errors.append(Error(message, id="django_verifactu.E003"))
    errors += [
        Error(f"VERIFACTU['SOFTWARE']: [{v.code}] {v.message}", id="django_verifactu.E003")
        for v in validate_software(software, date.today())
    ]
    # Every issue would fail: the taxpayers listed make IndicadorMultiplesOT S.
    several = len(conf.configured_taxpayers()) > 1
    hook = settings.VERIFACTU.get("MULTIPLE_TAXPAYERS")
    if several and hook is None and not software.multiple_taxpayers_possible:
        message = "VERIFACTU['SOFTWARE'] declares a single taxpayer, but TAXPAYERS has more"
        errors.append(Error(message, id="django_verifactu.E003"))
    return errors


@register()
def check_taxpayers(app_configs, **kwargs) -> list[CheckMessage]:
    verifactu = getattr(settings, "VERIFACTU", None)
    if not isinstance(verifactu, Mapping):
        return []
    messages = []
    if (hook := verifactu.get("MULTIPLE_TAXPAYERS")) is not None:
        messages += _check_function(hook, "MULTIPLE_TAXPAYERS", "django_verifactu.E005")
    taxpayers = verifactu.get("TAXPAYERS", {})
    if isinstance(taxpayers, str):
        return messages + _check_function(taxpayers, "TAXPAYERS", "django_verifactu.E004")
    if not isinstance(taxpayers, Mapping):
        message = "VERIFACTU['TAXPAYERS'] must be a dict or the dotted path of a function"
        return [*messages, Error(message, id="django_verifactu.E004")]
    for tax_id in taxpayers:
        messages += _check_taxpayer(tax_id)
    return messages


# Warnings only: one taxpayer's credentials must never stop sending for the others.
def _check_taxpayer(tax_id: str) -> list[CheckMessage]:
    label = f"VERIFACTU['TAXPAYERS']['{tax_id}']"
    try:
        taxpayer = conf.taxpayer(tax_id)
        client_ssl_context(taxpayer.certificate, taxpayer.password)
        password = taxpayer.password.encode()
        certificate = pkcs12.load_key_and_certificates(taxpayer.certificate, password)[1]
        violations = validate_header(
            taxpayer_tax_id=tax_id,
            taxpayer_name=taxpayer.name,
            representative=taxpayer.representative,
            verifactu_end_date=taxpayer.verifactu_end_date,
            today=date.today(),
        )
    except Exception as error:
        message = f"{label} is unusable: {type(error).__name__}: {error}"
        return [Warning(message, id="django_verifactu.W001")]
    problems = [f"[{v.code}] {v.message}" for v in violations]
    if certificate.not_valid_after_utc < datetime.now(UTC):
        problems.append("the certificate expired, so the AEAT refuses it")
    return [Warning(f"{label}: {problem}", id="django_verifactu.W001") for problem in problems]


def _check_function(path: str, name: str, code: str) -> list[CheckMessage]:
    if not isinstance(path, str):
        return [Error(f"VERIFACTU['{name}'] must be the dotted path of a function", id=code)]
    try:
        function = import_string(path)
    except Exception as error:
        message = f"VERIFACTU['{name}'] cannot be imported: {type(error).__name__}: {error}"
        return [Error(message, id=code)]
    if not callable(function):
        return [Error(f"VERIFACTU['{name}'] must name a function", id=code)]
    return []
