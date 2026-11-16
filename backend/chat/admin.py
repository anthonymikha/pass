from django.contrib import admin

from .models import Chat, ChatMember, Message

admin.site.register(Chat, list_display=("id", "type", "group", "club"))
admin.site.register(ChatMember, list_display=("chat", "user", "last_read_at"))
admin.site.register(Message, list_display=("chat", "sender", "session", "created_at"))
