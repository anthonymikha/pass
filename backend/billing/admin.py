from django.contrib import admin

from .models import CommissionRate, Payment

admin.site.register(Payment, list_display=("paid_at", "payer", "club", "coach", "amount", "currency", "method", "settled_at"))
admin.site.register(CommissionRate, list_display=("applies_to", "club", "coach", "min_count", "percent", "effective_from"))
