"""Messages from visitors about a published card («Знайшли помилку?»)."""
from django.conf import settings
from django.db import models


class ErrorReport(models.Model):
    KIND = [("date", "дата или время"), ("place", "место"), ("price", "цена или билеты"), ("cancelled", "событие отменено"),
            ("other", "другое")]
    STATUS = [("new", "новое"), ("done", "исправлено"), ("dismissed", "не подтвердилось")]
    event = models.ForeignKey("catalog.Event", verbose_name="событие", on_delete=models.CASCADE,
                              related_name="error_reports")
    site = models.ForeignKey("portals.Site", verbose_name="сайт", on_delete=models.CASCADE)
    kind = models.CharField("что не так", max_length=10, choices=KIND, default="other")
    message = models.TextField("сообщение", max_length=2000)
    email = models.EmailField("email для ответа", blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="пользователь", null=True, blank=True,
                             on_delete=models.SET_NULL)
    ip_hash = models.CharField(max_length=64, blank=True)
    status = models.CharField("статус", max_length=10, choices=STATUS, default="new", db_index=True)
    note = models.TextField("заметка модератора", blank=True)
    created_at = models.DateTimeField("получено", auto_now_add=True)

    class Meta:
        ordering = ["status", "-created_at"]
        verbose_name = "сообщение об ошибке"
        verbose_name_plural = "сообщения об ошибках"

    def __str__(self):
        return f"{self.get_kind_display()}: {self.event}"
