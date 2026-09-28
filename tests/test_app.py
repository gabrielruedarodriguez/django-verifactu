from datetime import date

import pytest
from django.apps import apps
from django.core.checks import run_checks
from django.core.management import call_command

from django_verifactu.aeat.domain import Party
from tests.certificates import fake_pkcs12


def test_app_loads_and_passes_system_checks():
    assert apps.get_app_config("django_verifactu").verbose_name == "VERI*FACTU"
    call_command("check")


def error_ids():
    return [error.id for error in run_checks() if error.id.startswith("django_verifactu")]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"USE_TZ": False}, ["django_verifactu.E001"]),
        ({"VERIFACTU": {"SOFTWARE": {}}}, ["django_verifactu.E002", "django_verifactu.E003"]),
    ],
)
def test_invalid_settings_are_reported(settings, change, expected):
    for name, value in change.items():
        setattr(settings, name, value)
    assert error_ids() == expected


def test_invalid_software_is_reported(settings):
    software = {**settings.VERIFACTU["SOFTWARE"], "system_id": "fa"}
    settings.VERIFACTU = {**settings.VERIFACTU, "SOFTWARE": software}
    assert error_ids() == ["django_verifactu.E003"]


def with_taxpayers(settings, taxpayers):
    settings.VERIFACTU = {**settings.VERIFACTU, "TAXPAYERS": taxpayers}


@pytest.mark.parametrize(
    "change",
    [
        {"password": "wrong"},
        {"certificate": "/nowhere/company.p12"},
        {"name": " "},
        {"representative": Party("Gestor", tax_id="12345678A")},
        {"verifactu_end_date": date(2099, 12, 31)},
        {"colour": "blue"},
        {"name": None},
        {"representative": {"name": "Gestor", "tax_id": "12345678Z"}},
        {"verifactu_end_date": "2026-12-31"},
        {"certificate": fake_pkcs12(expired=True)},
    ],
)
def test_taxpayers_with_problems_are_warned_about(settings, change):
    entry = {**settings.VERIFACTU["TAXPAYERS"]["89890001K"], **change}
    with_taxpayers(settings, {"89890001K": entry})
    assert error_ids() == ["django_verifactu.W001"]


def test_warnings_never_show_the_password(settings):
    entry = {**settings.VERIFACTU["TAXPAYERS"]["89890001K"], "password": "contrase\udcf1a-SECRET"}
    with_taxpayers(settings, {"89890001K": entry})
    [warning] = [m for m in run_checks() if m.id == "django_verifactu.W001"]
    assert "SECRET" not in warning.msg


def test_single_taxpayer_software_cannot_list_several(settings):
    software = {**settings.VERIFACTU["SOFTWARE"], "multiple_taxpayers_possible": False}
    settings.VERIFACTU = {**settings.VERIFACTU, "SOFTWARE": software}
    assert error_ids() == ["django_verifactu.E003"]
    alone = {"89890001K": settings.VERIFACTU["TAXPAYERS"]["89890001K"]}
    with_taxpayers(settings, alone)
    assert error_ids() == []


def test_taxpayers_are_keyed_by_nif(settings):
    with_taxpayers(settings, {"89890001A": settings.VERIFACTU["TAXPAYERS"]["89890001K"]})
    assert error_ids() == ["django_verifactu.W001"]


def test_credentials_can_come_from_a_provider(settings):
    with_taxpayers(settings, "tests.test_conf.provider")
    assert error_ids() == []


@pytest.mark.parametrize(
    "taxpayers",
    ["tests.missing.provider", "tests.settings.USE_TZ", ".provider", ["x"], lambda tax_id: None],
)
def test_invalid_providers_are_reported(settings, taxpayers):
    with_taxpayers(settings, taxpayers)
    assert error_ids() == ["django_verifactu.E004"]


@pytest.mark.parametrize(
    "hook", ["tests.missing.hook", "tests.settings.USE_TZ", ".hook", True, lambda tax_id: True]
)
def test_invalid_multiple_taxpayers_hooks_are_reported(settings, hook):
    settings.VERIFACTU = {**settings.VERIFACTU, "MULTIPLE_TAXPAYERS": hook}
    assert error_ids() == ["django_verifactu.E005"]


@pytest.mark.parametrize(
    "change", [{"name": " "}, {"version": "1" * 51}, {"system_id": ""}, {"system_id": "ABC"}]
)
def test_software_values_outside_the_schema_are_reported(settings, change):
    software = {**settings.VERIFACTU["SOFTWARE"], **change}
    settings.VERIFACTU = {**settings.VERIFACTU, "SOFTWARE": software}
    assert error_ids() == ["django_verifactu.E003"]
