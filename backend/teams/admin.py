from django.contrib import admin

from .models import Group, GroupMember

admin.site.register(Group, list_display=("name", "type", "owner", "coach", "sport"))
admin.site.register(GroupMember, list_display=("group", "user", "status"))
