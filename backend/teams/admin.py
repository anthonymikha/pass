from django.contrib import admin

from . import services
from .models import Group, GroupMember


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    """ACC-7, TEAM-34: a platform admin gives a team without a coach a new one, or deletes it."""

    list_display = ("name", "type", "created_by", "coach", "sport")
    list_filter = ("type", ("coach", admin.EmptyFieldListFilter))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.type == Group.Type.TEAM and obj.coach and "coach" in form.changed_data:
            services.seat_coach(obj)  # TEAM-35

    def delete_model(self, request, obj):
        services.delete_group(obj)  # TEAM-30: the chat stays, emptied of members

    def delete_queryset(self, request, queryset):
        for group in queryset:
            services.delete_group(group)


admin.site.register(GroupMember, list_display=("group", "user", "status"))
