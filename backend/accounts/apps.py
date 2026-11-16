from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self):
        from config.api import make_timestamps_strict

        make_timestamps_strict()
