from django.contrib import admin

from .models import Club, ClubCurrency, ClubMember, Court, CourtBlockout, CourtRate, Discount, Equipment, PriceOverride, Sport

admin.site.register(Sport, list_display=("name",))
admin.site.register(Club, list_display=("name", "owner", "currency", "timezone"))
admin.site.register(ClubMember, list_display=("club", "user", "role", "status", "expires_on"))
admin.site.register(ClubCurrency, list_display=("club", "currency", "exchange_rate"))
admin.site.register(Court, list_display=("name", "club", "slot_minutes", "is_active"))
admin.site.register(CourtRate, list_display=("court", "weekday", "start_time", "end_time", "price"))
admin.site.register(CourtBlockout, list_display=("court", "starts_on", "start_time", "end_time", "repeat", "repeat_until"))
admin.site.register(Equipment, list_display=("name", "club", "court", "quantity", "rental_price"))
admin.site.register(PriceOverride, list_display=("court_rate", "equipment", "currency", "price"))
admin.site.register(Discount, list_display=("club", "court", "user", "percent_off", "amount_off", "starts_at", "ends_at"))
