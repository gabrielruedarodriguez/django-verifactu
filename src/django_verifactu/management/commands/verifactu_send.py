import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from django_verifactu.sending import send_pending


class Command(BaseCommand):
    help = "Send the pending VERI*FACTU records to the AEAT."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true", help="keep sending until stopped")
        parser.add_argument("--interval", type=float, default=5, help="seconds between passes")
        parser.add_argument("--taxpayer", help="send only the records of this NIF")

    def handle(self, *, loop, interval, taxpayer, **options):
        self.stopping = False
        if loop:
            for signum in (signal.SIGTERM, signal.SIGINT):
                signal.signal(signum, self._stop)
        while True:
            for submission in send_pending(taxpayer_tax_id=taxpayer):
                taxpayer_tax_id = submission.installation.taxpayer_tax_id
                count = submission.lines.count()
                self.stdout.write(f"{taxpayer_tax_id}: {submission.outcome}, {count} records")
            if not loop:
                return
            self._wait(interval)
            if self.stopping:
                return
            close_old_connections()

    # Stops between passes: a submission in progress is always finished and stored.
    def _stop(self, signum, frame):
        self.stopping = True

    def _wait(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self.stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))
