from django import forms

from tenders.models import Company


class CompanyAdminForm(forms.ModelForm):
    username = forms.CharField(required=False)
    password = forms.CharField(required=False, widget=forms.PasswordInput(render_value=True))
    email = forms.EmailField(required=False)
    first_name = forms.CharField(required=False)
    last_name = forms.CharField(required=False)

    class Meta:
        model = Company
        fields = ['name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            for field_name in ['username', 'password', 'email', 'first_name', 'last_name']:
                self.fields[field_name].required = False
                self.fields[field_name].help_text = 'Used only when creating a new company account.'
        else:
            self.fields['username'].required = True
            self.fields['password'].required = True

    def clean(self):
        cleaned_data = super().clean()
        if self.instance and self.instance.pk:
            return cleaned_data

        if not cleaned_data.get('username'):
            self.add_error('username', 'Username is required when creating a company.')
        if not cleaned_data.get('password'):
            self.add_error('password', 'Password is required when creating a company.')
        return cleaned_data
