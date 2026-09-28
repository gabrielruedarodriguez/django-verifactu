from django.apps import AppConfig


class VerifactuConfig(AppConfig):
    name = "django_verifactu"
    verbose_name = "VERI*FACTU"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django_verifactu import checks  # noqa: F401
