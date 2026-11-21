from django.conf import settings
from django.core.management.base import BaseCommand

from config.storage import get_storage


class Command(BaseCommand):
    help = "Set the bucket's CORS rule to the app's own origin (docs/deployment.md, Storage). Safe to run at every start."

    def handle(self, *args, **options):
        origin = f"{'http' if settings.DEBUG else 'https'}://{settings.PASS_HOST}"
        get_storage().set_cors(origin)
        self.stdout.write(f"bucket CORS: {origin}")
