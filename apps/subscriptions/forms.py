from django import forms
from django.utils.translation import gettext_lazy as _


class SubscribeForm(forms.Form):
    channel = forms.ChoiceField(choices=[("email", "email"), ("telegram", "telegram")], initial="email",
                                widget=forms.HiddenInput)
    email = forms.EmailField(label=_("Ваш email"), required=False)
    city = forms.MultipleChoiceField(label=_("Міста"), required=False, widget=forms.CheckboxSelectMultiple)
    type = forms.MultipleChoiceField(label=_("Категорії"), required=False, widget=forms.CheckboxSelectMultiple)
    website = forms.CharField(required=False)

    def __init__(self, *a, cities=(), types=(), **kw):
        super().__init__(*a, **kw)
        self.fields["city"].choices = list(cities)
        self.fields["type"].choices = list(types)

    def clean(self):
        d = super().clean()
        if d.get("channel") == "email" and not d.get("email"):
            self.add_error("email", _("Вкажіть email."))
        return d


class RemindForm(forms.Form):
    occurrence = forms.IntegerField(widget=forms.HiddenInput)
    email = forms.EmailField(label=_("Ваш email"))
    website = forms.CharField(required=False)
