from django import forms
from .models import Invoice


class UploadForm(forms.Form):
    document = forms.FileField(label="Invoice document", help_text="PDF, JPEG or PNG; up to 10 MiB and 10 PDF pages.",
                               widget=forms.ClearableFileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png"}))


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ["supplier", "invoice_number", "invoice_date", "due_date", "currency", "total", "notes"]
        widgets = {"invoice_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
                   "due_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 4})}

    def clean(self):
        data = super().clean()
        if data.get("invoice_date") and data.get("due_date") and data["due_date"] < data["invoice_date"]:
            self.add_error("due_date", "Due date cannot precede invoice date.")
        return data


class SubmitForm(forms.Form):
    acknowledge_duplicate = forms.BooleanField(required=False, label="I acknowledge this possible duplicate and want to submit it.")


class ConfirmInvoiceForm(InvoiceForm):
    confirm_details = forms.BooleanField(label='I have checked these details against the invoice and confirm they are correct.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('supplier', 'invoice_number', 'invoice_date', 'currency', 'total'):
            self.fields[name].required = True


class ReturnForm(forms.Form):
    reason = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={"rows": 3}), label="Reason for returning")


class FilterForm(forms.Form):
    q = forms.CharField(required=False, label="Search supplier or number", max_length=200)
    status = forms.ChoiceField(required=False, choices=[("", "All statuses"), *Invoice.Status.choices])
    date_from = forms.DateField(required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))

    def clean(self):
        data = super().clean()
        if data.get("date_from") and data.get("date_to") and data["date_from"] > data["date_to"]:
            self.add_error("date_to", "End date must be on or after start date.")
        return data


class SpendingFilterForm(forms.Form):
    date_from = forms.DateField(required=False, label='From invoice date', widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(required=False, label='To invoice date', widget=forms.DateInput(attrs={'type': 'date'}))
    supplier = forms.CharField(required=False, max_length=200, label='Supplier contains')
    status = forms.ChoiceField(choices=[('submitted_approved', 'Submitted and approved'), ('submitted', 'Submitted only'),
                                      ('approved', 'Approved only'), ('all', 'All statuses (including drafts and returned)')])
    currency = forms.ChoiceField(choices=Invoice.CURRENCIES)
    granularity = forms.ChoiceField(choices=[('day', 'Daily'), ('week', 'Weekly'), ('month', 'Monthly'),
                                           ('quarter', 'Quarterly'), ('year', 'Yearly')])

    def clean(self):
        data = super().clean()
        if data.get('date_from') and data.get('date_to') and data['date_from'] > data['date_to']:
            self.add_error('date_to', 'End date must be on or after start date.')
        return data
