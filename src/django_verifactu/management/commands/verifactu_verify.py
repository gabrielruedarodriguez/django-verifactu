from django.core.management.base import BaseCommand, CommandError

from django_verifactu.verifying import verify


class Command(BaseCommand):
    help = "Verify the VERI*FACTU chains and, with --aeat, compare them with what the AEAT holds."

    def add_arguments(self, parser):
        parser.add_argument("--taxpayer", help="verify only this taxpayer (NIF)")
        parser.add_argument("--aeat", action="store_true", help="also query the AEAT")

    def handle(self, *args, taxpayer, aeat, **options):
        problems = verify(taxpayer_tax_id=taxpayer, aeat=aeat)
        for problem in problems:
            self.stdout.write(problem)
        if problems:
            raise CommandError(f"{len(problems)} problems found")
        self.stdout.write("no problems found")
