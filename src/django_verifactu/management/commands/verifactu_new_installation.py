from django.core.management.base import BaseCommand, CommandError

from django_verifactu.issuing import new_installation


class Command(BaseCommand):
    help = "Restart a taxpayer's VERI*FACTU chain with a new installation."

    def add_arguments(self, parser):
        parser.add_argument("taxpayer", help="the taxpayer's NIF")

    def handle(self, *args, taxpayer, **options):
        try:
            installation = new_installation(taxpayer)
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(f"{installation}: installation number {installation.number}")
