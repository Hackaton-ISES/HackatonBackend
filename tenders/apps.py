from django.apps import AppConfig


class TendersConfig(AppConfig):
    name = 'tenders'

    def ready(self):
        import tenders.signals  # noqa: F401
