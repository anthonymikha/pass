from django.contrib import admin

from .models import Exercise, ExerciseAssignment, ExerciseBodyArea, SleepLog, SorenessLog, UserAchievement

admin.site.register(SorenessLog, list_display=("user", "logged_on", "period", "body_area", "level"))
admin.site.register(SleepLog, list_display=("user", "sleep_start", "sleep_end", "source"))
admin.site.register(Exercise, list_display=("name", "kind", "min_soreness", "max_soreness"))
admin.site.register(ExerciseBodyArea, list_display=("exercise", "body_area"))
admin.site.register(ExerciseAssignment, list_display=("exercise", "user", "assigned_by", "due_on", "completed_at"))
admin.site.register(UserAchievement, list_display=("user", "achievement_code", "earned_at"))
