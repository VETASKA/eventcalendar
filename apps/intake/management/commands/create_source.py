from django.core.management.base import BaseCommand

from apps.intake.models import EventSource


class Command(BaseCommand):
    help = "Створити джерело і видати токен для API: create_source harvey --name 'Харві'. Токен показується один раз."

    def add_arguments(self, parser):
        parser.add_argument("code")
        parser.add_argument("--name", default="")
        parser.add_argument("--rotate", action="store_true", help="Видати новий токен (старий перестане працювати)")

    def handle(self, code, name, rotate, **_):
        src, created = EventSource.objects.get_or_create(code=code, defaults={"name": name or code})
        if not created and src.token_hash and not rotate:
            self.stdout.write("Токен уже видано. Щоб замінити: --rotate")
            return
        token = src.issue_token()
        self.stdout.write(token)
