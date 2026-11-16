from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Connection, User, UserBlockout


# Django's stock user forms work here: the admin rebuilds them for this model via modelform_factory,
# so only the username-based fieldsets need replacing.
@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "phone", "avatar", "timezone", "managed_by")}),
        ("Coach", {"fields": ("is_coach", "coach_bio", "coach_rate", "coach_currency")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "created_at")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "full_name", "managed_by", "usable_password", "password1", "password2")}),
    )
    readonly_fields = ("created_at",)
    list_display = ("email", "full_name", "is_coach", "managed_by", "is_staff")
    search_fields = ("email", "full_name", "phone")
    ordering = ("email",)


admin.site.register(Connection, list_display=("user", "other_user", "type", "status"))
admin.site.register(UserBlockout, list_display=("user", "weekday", "on_date", "start_time", "end_time"))
