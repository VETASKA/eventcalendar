from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.subscriptions import telegram


class Command(BaseCommand):
    help = "Подключить Telegram-бота: telegram_setup https://eventcalendar.com.ua (нужны TELEGRAM_* в .env)"

    def add_arguments(self, parser):
        parser.add_argument("base_url")

    def handle(self, base_url, **_):
        if not telegram.enabled() or not settings.TELEGRAM_WEBHOOK_SECRET:
            raise CommandError("Заполните TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_NAME и TELEGRAM_WEBHOOK_SECRET в .env")
        url = base_url.rstrip("/") + f"/telegram/webhook/{settings.TELEGRAM_WEBHOOK_SECRET}/"
        telegram.set_webhook(url)
        self.stdout.write(self.style.SUCCESS(f"Бот подключён: @{settings.TELEGRAM_BOT_NAME}"))
