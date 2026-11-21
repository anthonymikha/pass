from django.core.management.base import BaseCommand

from billing.services import bill_ended_sessions
from bookings.services import send_rpe_reminders


class Command(BaseCommand):
    help = "One scheduler tick (NOTE-30): run every 60 seconds, safe to repeat and to skip."

    def handle(self, *args, **options):
        billed = bill_ended_sessions()  # NOTE-33: the downward call to billing allowed by docs/backend/README.md
        sent = send_rpe_reminders()
        self.stdout.write(f"sessions billed: {billed}, rpe reminders: {sent}")
