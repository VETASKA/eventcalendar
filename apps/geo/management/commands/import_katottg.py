from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.geo.katottg import import_katottg


class Command(BaseCommand):
    help = "Імпорт КАТОТТГ (XLSX з сайту Мінрозвитку або CSV): import_katottg kodyfikator.xlsx --version 2026-05"

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--version", required=True, help="Дата / номер знімка, напр. 2026-05-14")

    def handle(self, path, version, **_):
        p = Path(path)
        if not p.exists():
            raise CommandError(f"файл не знайдено: {p}")
        stats = import_katottg(p, version)
        self.stdout.write(self.style.SUCCESS(" ".join(f"{k}={v}" for k, v in stats.items())))
