from django import forms
from django.contrib import admin

from .models import CommissionRate, Payment


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["settled_at"]

    def clean_settled_at(self):
        settled_at = self.cleaned_data["settled_at"]
        if settled_at and self.instance.paid_at is None:
            raise forms.ValidationError("A payment that is still due cannot be settled.")  # COM-10
        return settled_at


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """ACC-7, COM-10, PAY-22: the only thing an admin changes on a payment is `settled_at`; none are added or deleted."""

    form = PaymentForm
    list_display = ("paid_at", "payer", "club", "coach", "amount", "currency", "method", "settled_at")
    list_filter = ("currency", "settled_at")
    fields = ("session", "payer", "club", "coach", "amount", "currency", "platform_fee", "method", "paid_at", "created_at",
              "settled_at")
    readonly_fields = ("session", "payer", "club", "coach", "amount", "currency", "platform_fee", "method", "paid_at",
                       "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(CommissionRate, list_display=("applies_to", "club", "coach", "min_count", "percent", "effective_from"))
