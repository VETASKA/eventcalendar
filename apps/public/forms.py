from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from apps.feedback.models import ErrorReport

KIND_UK = [("date", _("Дата або час")), ("place", _("Місце")), ("price", _("Ціна або квитки")),
           ("cancelled", _("Подію скасовано")), ("other", _("Інше"))]


class Honeypot(forms.Form):
    # bots fill every field; people never see this one
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    def is_bot(self) -> bool:
        return bool(self.data.get("website"))


class ErrorReportForm(Honeypot, forms.ModelForm):
    kind = forms.ChoiceField(label=_("Що не так"), choices=KIND_UK, initial="other")
    message = forms.CharField(label=_("Опишіть, будь ласка"), max_length=2000,
                              widget=forms.Textarea(attrs={"rows": 4, "placeholder": _("Наприклад: подію перенесли на 12 березня")}))
    email = forms.EmailField(label=_("Email, якщо хочете відповідь"), required=False)

    class Meta:
        model = ErrorReport
        fields = ["kind", "message", "email"]


class RegisterForm(Honeypot, forms.Form):
    name = forms.CharField(label=_("Ваше імʼя"), max_length=150)
    email = forms.EmailField(label=_("Email"))
    password = forms.CharField(label=_("Пароль"), widget=forms.PasswordInput, min_length=10,
                               help_text=_("Не менше 10 символів"))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError(_("Цей email уже зареєстровано. Увійдіть."))
        return email

    def clean(self):
        data = super().clean()
        if data.get("password") and data.get("email"):
            try:
                password_validation.validate_password(data["password"], User(username=data["email"], email=data["email"]))
            except forms.ValidationError as e:
                self.add_error("password", e)
        return data


class LoginForm(forms.Form):
    email = forms.EmailField(label=_("Email"))
    password = forms.CharField(label=_("Пароль"), widget=forms.PasswordInput)


class ClaimForm(forms.Form):
    org_name = forms.CharField(label=_("Організація або бренд"), max_length=300)
    role = forms.CharField(label=_("Ваша роль"), max_length=200, help_text=_("Наприклад: організатор, менеджер, PR"))
    phone = forms.CharField(label=_("Телефон для звʼязку"), max_length=40)
    evidence = forms.CharField(label=_("Чим можете підтвердити"), max_length=2000, required=False,
                               widget=forms.Textarea(attrs={"rows": 4}),
                               help_text=_("Посилання на сторінку, де вас вказано, пошта на домені організатора, "
                                           "соцмережі події — усе, що допоможе модератору."))


class SuggestForm(Honeypot, forms.Form):
    url = forms.URLField(label=_("Посилання на подію"), max_length=1000, assume_scheme="https",
                         widget=forms.URLInput(attrs={"placeholder": "https://…", "autocomplete": "off"}))
    email = forms.EmailField(label=_("Ваш email"), required=False, help_text=_("Якщо хочете дізнатися, коли подію опублікують"))
    date = forms.DateField(label=_("Дата"), required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    city = forms.CharField(label=_("Місто"), max_length=100, required=False)
    type = forms.ChoiceField(label=_("Категорія"), required=False)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        from apps.catalog.models import EventType
        from apps.core.i18n import name_in
        self.fields["type"].choices = [("", "—")] + [(t.code, name_in(t.names, fallback=t.code))
                                                      for t in EventType.objects.filter(is_active=True)]


class ClaimMethodMixin(forms.Form):
    method = forms.ChoiceField(
        label=_("Як підтвердите, що подія ваша"), widget=forms.RadioSelect, initial="file",
        choices=[("file", _("Файл на сайті події — найшвидше")),
                 ("email", _("Лист на пошту з домену сайту події")),
                 ("manual", _("Перевірка модератором вручну"))])


class CorporateEmailForm(forms.Form):
    email = forms.EmailField(label=_("Пошта на домені сайту події"))


class OrganizerEventForm(forms.Form):
    title = forms.CharField(label=_("Назва"), max_length=300)
    summary = forms.CharField(label=_("Короткий анонс"), max_length=600, required=False,
                              widget=forms.Textarea(attrs={"rows": 3}), help_text=_("1–3 речення своїми словами"))
    format = forms.ChoiceField(label=_("Формат"), choices=[("offline", _("Офлайн")), ("online", _("Онлайн")),
                                                          ("hybrid", _("Гібрид"))])
    event_type = forms.ChoiceField(label=_("Категорія"))
    registration_url = forms.URLField(label=_("Посилання на реєстрацію або квитки"), required=False, max_length=1000,
                                      assume_scheme="https")
    price_text = forms.CharField(label=_("Ціна"), max_length=120, required=False)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        from apps.catalog.models import EventType
        from apps.core.i18n import name_in
        self.fields["event_type"].choices = [(t.code, name_in(t.names, fallback=t.code))
                                             for t in EventType.objects.filter(is_active=True)]


class SessionForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    start_date = forms.DateField(label=_("Дата"), widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    end_date = forms.DateField(label=_("До (якщо кілька днів)"), required=False,
                               widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    start_time = forms.TimeField(label=_("Початок"), required=False, widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}))
    end_time = forms.TimeField(label=_("Кінець"), required=False, widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}))
    city = forms.ChoiceField(label=_("Місто"), required=False)
    venue = forms.CharField(label=_("Місце проведення"), max_length=300, required=False)
    status = forms.ChoiceField(label=_("Статус"), initial="scheduled", choices=[("scheduled", _("За планом")), ("rescheduled", _("Перенесено")),
                                                          ("postponed", _("Перенесено, нова дата уточнюється")),
                                                          ("cancelled", _("Скасовано"))])
    DELETE = forms.BooleanField(label=_("Видалити"), required=False)

    def __init__(self, *a, cities=(), **kw):
        super().__init__(*a, **kw)
        self.fields["city"].choices = [("", "—")] + list(cities)

    def clean(self):
        d = super().clean()
        if d.get("start_date") and d.get("end_date") and d["end_date"] < d["start_date"]:
            self.add_error("end_date", _("Дата закінчення раніше за початок."))
        return d


SessionFormSet = forms.formset_factory(SessionForm, extra=1, max_num=20)
