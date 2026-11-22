from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.models import User

from apps.feedback.models import ErrorReport

KIND_UK = [("date", "Дата або час"), ("place", "Місце"), ("price", "Ціна або квитки"),
           ("cancelled", "Подію скасовано"), ("other", "Інше")]


class Honeypot(forms.Form):
    # bots fill every field; people never see this one
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    def is_bot(self) -> bool:
        return bool(self.data.get("website"))


class ErrorReportForm(Honeypot, forms.ModelForm):
    kind = forms.ChoiceField(label="Що не так", choices=KIND_UK, initial="other")
    message = forms.CharField(label="Опишіть, будь ласка", max_length=2000,
                              widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Наприклад: подію перенесли на 12 березня"}))
    email = forms.EmailField(label="Email, якщо хочете відповідь", required=False)

    class Meta:
        model = ErrorReport
        fields = ["kind", "message", "email"]


class RegisterForm(Honeypot, forms.Form):
    name = forms.CharField(label="Ваше імʼя", max_length=150)
    email = forms.EmailField(label="Email")
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput, min_length=10,
                               help_text="Не менше 10 символів")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("Цей email уже зареєстровано. Увійдіть.")
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
    email = forms.EmailField(label="Email")
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput)


class ClaimForm(forms.Form):
    org_name = forms.CharField(label="Організація або бренд", max_length=300)
    role = forms.CharField(label="Ваша роль", max_length=200, help_text="Наприклад: організатор, менеджер, PR")
    phone = forms.CharField(label="Телефон для звʼязку", max_length=40)
    evidence = forms.CharField(label="Чим можете підтвердити", max_length=2000, widget=forms.Textarea(attrs={"rows": 4}),
                               help_text="Посилання на сторінку, де вас вказано, пошта на домені організатора, "
                                         "соцмережі події — усе, що допоможе модератору.")
