from django.core.management.base import BaseCommand

from bookings.services import send_rpe_reminders


class Command(BaseCommand):
    help = "One scheduler tick (NOTE-30): run every 60 seconds, safe to repeat and to skip."

    def handle(self, *args, **options):
        sent = send_rpe_reminders()
        self.stdout.write(f"rpe reminders: {sent}")
