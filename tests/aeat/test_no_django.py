import subprocess
import sys

IMPORT_EVERY_AEAT_MODULE = """
import importlib, pkgutil, sys
import django_verifactu.aeat as aeat
for module in pkgutil.walk_packages(aeat.__path__, "django_verifactu.aeat."):
    importlib.import_module(module.name)
assert "django" not in sys.modules
"""


def test_aeat_core_never_imports_django():
    subprocess.run([sys.executable, "-c", IMPORT_EVERY_AEAT_MODULE], check=True)
