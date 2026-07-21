from django import forms


class DocumentDeliveryForm(forms.Form):
    recipient_name = forms.CharField(max_length=255)
    recipient_email = forms.EmailField()
