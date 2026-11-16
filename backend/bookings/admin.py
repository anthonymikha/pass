from django.contrib import admin

from .models import Recording, RecordingTag, Session, SessionParticipant, SessionRental

admin.site.register(Session, list_display=("starts_at", "court", "kind", "status", "booked_by", "coach", "price", "currency"))
admin.site.register(SessionParticipant, list_display=("session", "user", "status", "rpe"))
admin.site.register(SessionRental, list_display=("session", "equipment", "quantity", "price", "status"))
admin.site.register(Recording, list_display=("storage_key", "session", "uploaded_by", "duration_seconds"))
admin.site.register(RecordingTag, list_display=("label", "recording", "start_second", "end_second", "created_by"))
